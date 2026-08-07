"""Catchment endpoints (Water Intelligence, tickets M4-003/M4-004),
mirroring `app/api/farms.py`'s exact pattern: every write is role-gated,
the creating officer's identity always comes from the authenticated
JWT — never the request body — and the authoritative area is always
computed server-side via PostGIS, never trusted from the client.

Role-gated to `PROGRAMME_OFFICER`/`PROGRAMME_ADMIN` — Water
Intelligence's own roles (Blueprint v2 D8), not Service 1's bank roles
(`CREDIT_OFFICER`/`BRANCH_MANAGER`).

`POST /catchments` (manual draw, M4-003) and `POST /catchments/upload`
(file upload, M4-004) both converge on `_persist_catchment()` below —
Blueprint v2 D2's "one validation boundary, two ways in" made concrete:
the two endpoints differ only in *how* a validated `GeoJSONMultiPolygon`
was obtained (directly from the JSON request body vs. parsed from an
uploaded file via `boundary_parser.py`, M4-002) and which
`DelineationMethod` that implies — every other rule (referenced-id
validation, duplicate-name scoping, area computation and bounds
checking, row construction) is the same code, not a re-implementation.

`GET /catchments` / `GET /catchments/{id}` (ticket M4-005) deliberately
diverge from `app/api/farms.py`'s own GET-endpoint pattern in one way:
Farm's reads use the role-agnostic `get_current_user` (any authenticated
bank user may read), because Service 1's entire user population is bank
staff already implicitly scoped by branch. Water Intelligence shares the
same auth system with a materially different user population (bank
roles have no legitimate reason to see catchment data at all), so reads
here are role-gated exactly like writes
(`PROGRAMME_OFFICER`/`PROGRAMME_ADMIN`) — giving a real, distinct 403 for
a wrong-product-entirely caller, separate from the 404 IDOR-safe
not-found response `user_can_access_owned_resource`-style scoping
produces for a right-role caller viewing someone else's catchment.

`POST /catchments/{id}/water-reports` (ticket M4-006; wired to a real
pipeline in M5-002) mirrors `app/api/reports.py`'s `trigger_report`
pattern for the trigger endpoint itself: same ownership check shape,
same `pg_advisory_xact_lock`-guarded in-flight-job check (keyed on
`'catchment_water_report'` instead of `'farm_report'`), same
Job-then-BackgroundTasks split, same "never leave a job stuck at PENDING
with no error_message" discipline.

`_run_water_report_job` (M5-002) is a deliberate STRUCTURAL deviation
from `app/api/reports.py`'s `_run_report_job`/`generate_farm_report`
split, not an oversight: Service 1 splits "construct the provider" from
"own RUNNING/DONE/FAILED and run the pipeline" across two functions,
because `generate_farm_report()` itself manages the Job row. Water
Intelligence's `generate_water_report()` (`app/services/hydrology/
water_report_generator.py`, M5-001) deliberately owns no Job/JobStatus
writes at all — its own docstring calls this "orchestrate only" — and
M5-002's own "Do NOT: Modify orchestrator" instruction forbids changing
that now. So `_run_water_report_job` below is the single function that
does both jobs Service 1 splits: constructs real providers (same
to_thread/separately-caught-failure reasoning as `_run_report_job`), and
owns every RUNNING/DONE/FAILED transition (the same job that
`generate_farm_report` does internally for Service 1). The lifecycle
guarantee is the same; which function owns which half of it is not.

One further, flagged difference from `_run_report_job`'s DONE handling:
`generate_farm_report` overwrites `Job.entity_id` with the resulting
`risk_score.id` once DONE, because a farm report has exactly one result
artifact. A water report has two sibling artifacts
(`WaterBalanceResult` and `RechargeStressScore`, same `catchment_id` +
`computed_at`, no single id representing "the report") — so
`Job.entity_id` here is left as `catchment_id` throughout, never
overwritten. Both artifacts remain reachable by `catchment_id` (each
has its own `catchment_id`-indexed lookup) once a future ticket adds a
water-report-fetch endpoint; inventing a single combined id or a new
response shape now would mean modifying schemas/APIs, both forbidden by
M5-002's own scope.

Ownership scoping (`_visible_to` below) is creator-based
(`created_by == current_user.id`), not organization-membership-based:
`AppUser` has no `organization_id` (only Service 1's `branch_id`), so
"same organization" cannot be checked against the *requesting user's*
own membership — only against the *catchment's own* `organization_id`
tag, which says nothing about who else belongs to that organization.
Implementing genuine multi-user organization sharing needs a
user-to-organization link this ticket cannot add (`Do NOT: Modify
schemas`) — consistent with Blueprint v2 D8's own stated MVP position
("not yet enforced... deferred until a second organization actually
needs to share a deployment"), not a gap introduced here.

`GET /catchments/{id}/water-reports` (ticket M5-003) — the read side of
M5-002's write pipeline, same IDOR-safe ownership check as
`get_catchment`. "Latest completed report" is anchored on the `Job`,
not the result rows: the latest `JobType.CATCHMENT_WATER_REPORT` row
with `status == DONE` for this catchment defines what counts as
"completed" at all (404 if none), then the latest `WaterBalanceResult`/
`RechargeStressScore` by `computed_at` are read as that job's output.
There is no FK correlating a specific `Job` to a specific result pair —
`Job.entity_id` is deliberately left as `catchment_id`, never
overwritten (see the M5-002 paragraph above) — so this correlation
relies on an invariant the system already guarantees elsewhere, not a
new assumption: `POST /catchments/{id}/water-reports`' own
`pg_advisory_xact_lock`-guarded in-flight-job check (M4-006) never lets
two water-report jobs for the same catchment run concurrently, so
successive completed runs are strictly ordered — the Nth job's DONE
transition always immediately follows the Nth result pair's persist.
"Latest DONE job" and "latest `computed_at` result pair" therefore
always name the same run.
"""

from __future__ import annotations

import asyncio
import json
import logging
from uuid import UUID

from fastapi import APIRouter, BackgroundTasks, Depends, File, Form, HTTPException, Query, Response, UploadFile, status
from geoalchemy2 import Geography
from geoalchemy2.functions import ST_Area, ST_AsGeoJSON
from geoalchemy2.shape import from_shape
from sqlalchemy import and_, cast, func, select, text
from sqlalchemy.ext.asyncio import AsyncSession

from app.api.deps import require_role
from app.database.base import AsyncSessionLocal
from app.database.session import get_db
from app.models.admin import AdminBoundary
from app.models.catchment import Catchment
from app.models.enums import DelineationMethod, JobStatus, JobType, UserRole
from app.models.job import Job
from app.models.organization import Organization
from app.models.user import AppUser
from app.models.water_balance import RechargeStressScore, WaterBalanceResult
from app.schemas.catchment import (
    CatchmentCreateRequest,
    CatchmentDetailResponse,
    CatchmentResponse,
    CatchmentUploadRequest,
    GeoJSONMultiPolygon,
)
from app.schemas.job import JobStatusResponse
from app.schemas.report import ReportTriggerResponse
from app.schemas.water_report import (
    RechargeStressScoreResponse,
    WaterBalanceResultResponse,
    WaterReportDetailResponse,
    WaterReportHistoryItem,
)
from app.services.boundary_parser import BoundaryParseError, parse_boundary_file
from app.services.hydrology.engine import WaterBalanceEngine
from app.services.hydrology.gee_hydrology_provider import GEEHydrologyProvider
from app.services.hydrology.recharge_stress import RechargeStressEngine
from app.services.hydrology.water_report_generator import generate_water_report
from app.services.satellite.gee_provider import GeeProvider

router = APIRouter(prefix="/catchments", tags=["Catchments"])
logger = logging.getLogger(__name__)

_DEFAULT_PAGE_SIZE = 50
_MAX_PAGE_SIZE = 200

# The exact bounds Catchment's own chk_catchment_area CHECK constraint
# enforces (app/models/catchment.py) — checked here too so a client gets
# a clear 422 with the actual computed area, not an opaque database
# IntegrityError after the row was already (attempted to be) written.
_MIN_CATCHMENT_AREA_HA = 0.5
_MAX_CATCHMENT_AREA_HA = 50000.0

# Sub-pixel disclosure thresholds (Blueprint v2 D9/Part 5). Below these
# areas the corresponding input is not really a measurement OF this
# catchment — it is a regional value the catchment happens to sit inside,
# and the report must say so rather than present a falsely precise
# per-village figure.
#
# CHIRPS rainfall: ~0.05 degree grid, one pixel ~= 5.5 km ~= 3,000 ha.
# A typical Raichur village is ~140 ha — roughly 1/20th of a single
# rainfall pixel — so this flag is expected to be the common case, not
# an edge case, for the village-scale catchments this service targets.
_RAINFALL_PIXEL_AREA_HA = 3000.0

# MODIS MOD16A2 ET: 500 m native pixel = 25 ha. The 5x5-pixel (~25 ha)
# floor is Blueprint v2 D9's own stated threshold: below it, too few
# whole pixels fall inside the catchment for the spatial mean to describe
# it rather than its surroundings.
_ET_PIXEL_FLOOR_HA = 25.0


def _derive_resolution_flags(area_ha: float) -> list[str]:
    """Which inputs are too coarse to resolve a catchment of this size.

    Pure and area-only by design: these flags are computed once at
    creation and copied unchanged into every downstream report (the
    engine explicitly never re-derives them), so they must not depend on
    anything that can drift between creation and report time.

    Returned in a stable order so a catchment's flags are comparable
    across reports and diffable in tests.
    """
    flags: list[str] = []
    if area_ha < _RAINFALL_PIXEL_AREA_HA:
        flags.append("rainfall_sub_pixel")
    if area_ha < _ET_PIXEL_FLOOR_HA:
        flags.append("et_sub_pixel")
    return flags

# Same generic, safe, non-internal message on every water-report failure
# path below — provider construction, orchestrator/pipeline failure,
# alike — mirroring app/api/reports.py's _GENERIC_FAILURE_MESSAGE
# exactly: full exception detail goes to the server log only (see every
# logger.exception call below), the client/Job.error_message never see
# more than this.
_GENERIC_FAILURE_MESSAGE = "Water report generation failed. Please retry; contact support if this persists."


@router.post("", response_model=CatchmentResponse, status_code=status.HTTP_201_CREATED)
async def create_catchment(
    payload: CatchmentCreateRequest,
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> CatchmentResponse:
    """Persist a manually-drawn catchment boundary. Geometry validity,
    closedness, coordinate range, hole structure, and total vertex count
    are already enforced by `CatchmentCreateRequest` at the
    request-parsing boundary (`app/schemas/catchment.py`, M4-001).
    """
    catchment = await _persist_catchment(
        db,
        name=payload.name,
        geometry=payload.geometry,
        organization_id=payload.organization_id,
        admin_boundary_id=payload.admin_boundary_id,
        delineation_method=DelineationMethod.MANUAL,
        created_by=current_user.id,
    )
    return CatchmentResponse.model_validate(catchment)


@router.post("/upload", response_model=CatchmentResponse, status_code=status.HTTP_201_CREATED)
async def upload_catchment(
    file: UploadFile = File(...),
    name: str = Form(...),
    organization_id: UUID | None = Form(None),
    admin_boundary_id: UUID | None = Form(None),
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> CatchmentResponse:
    """Persist a catchment boundary from an uploaded GeoJSON, KML, or
    zipped-Shapefile file (`boundary_parser.py`, M4-002) — everything
    after the file is parsed into a `GeoJSONMultiPolygon` is identical to
    `create_catchment()` above, via the shared `_persist_catchment()`.

    `name`/`organization_id`/`admin_boundary_id` arrive as multipart form
    fields (not a JSON body — this is a file upload), but are still
    validated through `CatchmentUploadRequest` (M4-001) before use, the
    same schema-level length/type checks `create_catchment()` gets for
    free from `CatchmentCreateRequest` — not re-implemented here.
    """
    metadata = CatchmentUploadRequest.model_validate(
        {"name": name, "organization_id": organization_id, "admin_boundary_id": admin_boundary_id}
    )

    content = await file.read()
    try:
        geometry: GeoJSONMultiPolygon = parse_boundary_file(file.filename or "", content)
    except BoundaryParseError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, detail=str(exc)) from exc

    catchment = await _persist_catchment(
        db,
        name=metadata.name,
        geometry=geometry,
        organization_id=metadata.organization_id,
        admin_boundary_id=metadata.admin_boundary_id,
        delineation_method=DelineationMethod.UPLOAD,
        created_by=current_user.id,
    )
    return CatchmentResponse.model_validate(catchment)


@router.get("", response_model=list[CatchmentResponse])
async def list_catchments(
    response: Response,
    limit: int = Query(_DEFAULT_PAGE_SIZE, ge=1, le=_MAX_PAGE_SIZE),
    offset: int = Query(0, ge=0),
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[CatchmentResponse]:
    """Every catchment the caller created, newest first. Scoped by
    `created_by` (see module docstring for why, not organization
    membership) — a query that is IDOR-safe by construction: the WHERE
    clause itself excludes every other user's catchments, so there is no
    separate check to forget.

    Pagination via `limit`/`offset` query params (default 50, capped at
    200 — "keep queries efficient" means bounding page size, not just
    indexing); total count is returned as the `X-Total-Count` response
    header rather than a wrapper response body, so this endpoint's
    response can stay a plain `list[CatchmentResponse]` without adding a
    new schema type (`Do NOT: Modify schemas`).
    """
    total = await db.scalar(select(func.count()).select_from(Catchment).where(Catchment.created_by == current_user.id))
    response.headers["X-Total-Count"] = str(total or 0)

    rows = (
        (
            await db.execute(
                select(Catchment)
                .where(Catchment.created_by == current_user.id)
                .order_by(Catchment.created_at.desc())
                .limit(limit)
                .offset(offset)
            )
        )
        .scalars()
        .all()
    )
    return [CatchmentResponse.model_validate(row) for row in rows]


@router.get("/{catchment_id}", response_model=CatchmentDetailResponse)
async def get_catchment(
    catchment_id: UUID,
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> CatchmentDetailResponse:
    """A single catchment by id — 404 for both "doesn't exist" and
    "exists but isn't yours", the same `app/api/farms.py::get_farm`
    IDOR-safe convention: a resource outside the caller's scope must be
    indistinguishable from one that was never created at all, never
    revealed via a 403 that would confirm the id is real.

    Returns the analysed geometry alongside the metadata (the list
    endpoint deliberately does not — see `CatchmentDetailResponse`), so a
    report can draw the exact area it was computed over rather than
    approximating it with the village boundary.
    """
    catchment = await db.get(Catchment, catchment_id)
    if catchment is None or catchment.created_by != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Catchment not found")

    geometry_json = (
        await db.execute(select(ST_AsGeoJSON(Catchment.geometry)).where(Catchment.id == catchment_id))
    ).scalar_one()

    return CatchmentDetailResponse(
        **CatchmentResponse.model_validate(catchment).model_dump(),
        geometry=json.loads(geometry_json),
    )


async def _run_water_report_job(job_id: UUID, catchment_id: UUID) -> None:
    """Background-task entry point for a triggered water report (M5-002).
    See the module docstring's "POST /catchments/{id}/water-reports"
    paragraph for why this single function owns both provider
    construction AND every Job status transition, unlike
    `app/api/reports.py`'s `_run_report_job`/`generate_farm_report` split.

    GEEHydrologyProvider()/GeeProvider() are constructed here, lazily,
    only once this actually runs — never in the request handler — for
    the identical reason `_run_report_job`'s own docstring gives:
    `BackgroundTasks.add_task()` evaluates its arguments immediately when
    scheduled, so a pre-built provider would trigger real Earth Engine
    authentication synchronously inside the request. Both are wrapped in
    `asyncio.to_thread()` because `ee.Initialize()` is a blocking network
    call with no async variant, run on a worker thread so it doesn't
    block this process's event loop even inside a background task — and
    a construction failure (bad/unreadable credentials) is caught here,
    separately from the pipeline's own try/except below, so it fails the
    job immediately instead of leaving it stuck (the exact DEPLOY-1
    failure mode `_run_report_job`'s docstring documents and fixes for
    Service 1, reused here unchanged).
    """
    try:
        hydrology_provider = await asyncio.to_thread(GEEHydrologyProvider)
        satellite_provider = await asyncio.to_thread(GeeProvider)
    except Exception:
        logger.exception(
            "water_report_provider_initialization_failed",
            extra={"job_id": str(job_id), "catchment_id": str(catchment_id)},
        )
        await _fail_water_report_job(job_id, _GENERIC_FAILURE_MESSAGE)
        return

    async with AsyncSessionLocal() as db:
        job = await db.get(Job, job_id)
        if job is None:
            return
        job.status = JobStatus.RUNNING
        await db.commit()

        try:
            await generate_water_report(
                db,
                catchment_id=catchment_id,
                hydrology_provider=hydrology_provider,
                satellite_provider=satellite_provider,
                water_balance_engine=WaterBalanceEngine(),
                recharge_stress_engine=RechargeStressEngine(),
            )
        except Exception:
            # Full detail goes to the server log only; the job row (and
            # therefore the API) only ever exposes the same generic
            # message every other failure path here uses. A defensive
            # rollback: generate_water_report()'s own persistence-failure
            # branch already rolls back before re-raising (see its
            # module docstring), so this is a safe no-op in that case —
            # but a provider/engine failure never reaches that branch at
            # all (nothing was added to the session yet), so this is the
            # only rollback guaranteeing a clean session before the
            # FAILED write below.
            logger.exception(
                "water_report_generation_failed",
                extra={"job_id": str(job_id), "catchment_id": str(catchment_id)},
            )
            await db.rollback()
            await _fail_water_report_job(job_id, _GENERIC_FAILURE_MESSAGE, db=db)
            return

        # Re-fetched, not reused: generate_water_report()'s own internal
        # commit (persisting WaterBalanceResult/RechargeStressScore)
        # expires every object already loaded in this session — a plain
        # `AsyncSession`, unlike a sync Session, cannot transparently
        # re-fetch an expired attribute on access, so `job` must be
        # re-loaded via an awaited db.get() before it's touched again.
        job = await db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.DONE
            # entity_id is deliberately left as catchment_id, not
            # overwritten — see module docstring for why (two sibling
            # result artifacts, no single id to overwrite it with).
            await db.commit()


async def _fail_water_report_job(job_id: UUID, message: str, *, db: AsyncSession | None = None) -> None:
    """Shared terminal-FAILED write, callable either with an existing
    session (the pipeline-failure path above, which must reuse its
    already-open session rather than open a second one mid-job) or with
    none (the provider-construction-failure path, which has no session
    yet at all)."""
    if db is not None:
        job = await db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = message
            await db.commit()
        return

    async with AsyncSessionLocal() as fresh_db:
        job = await fresh_db.get(Job, job_id)
        if job is not None:
            job.status = JobStatus.FAILED
            job.error_message = message
            await fresh_db.commit()


@router.post(
    "/{catchment_id}/water-reports", response_model=ReportTriggerResponse, status_code=status.HTTP_202_ACCEPTED
)
async def trigger_water_report(
    catchment_id: UUID,
    background_tasks: BackgroundTasks,
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> ReportTriggerResponse:
    """Create a water-report job for a catchment and schedule its
    background run — job creation only, per this ticket's scope (see the
    module docstring). Mirrors `app/api/reports.py::trigger_report`
    field-for-field: same IDOR-safe ownership check, same
    advisory-lock-guarded duplicate-in-flight-job check, same
    Job-then-BackgroundTasks split, same `ReportTriggerResponse` shape
    (reused as-is, not a new schema — `Do NOT: Modify schemas`).
    """
    catchment = await db.get(Catchment, catchment_id)
    if catchment is None or catchment.created_by != current_user.id:
        # Same not-found-vs-forbidden discipline as get_catchment above:
        # a catchment outside the caller's own scope must be
        # indistinguishable from one that doesn't exist at all.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Catchment not found")

    # Transaction-scoped advisory lock keyed on this catchment, exactly
    # like trigger_report's farm-scoped lock — closes the same TOCTOU
    # race (two concurrent triggers both passing the in-flight check
    # before either commits). A distinct lock namespace
    # ('catchment_water_report' vs 'farm_report') so the two services'
    # locks can never collide on the same hashtext() key space.
    await db.execute(
        text("SELECT pg_advisory_xact_lock(hashtext('catchment_water_report'), hashtext(:catchment_id))"),
        {"catchment_id": str(catchment_id)},
    )

    in_flight = await db.execute(
        select(Job).where(
            Job.type == JobType.CATCHMENT_WATER_REPORT,
            Job.entity_id == catchment_id,
            Job.status.in_([JobStatus.PENDING, JobStatus.RUNNING]),
        )
    )
    in_flight_job = in_flight.scalar_one_or_none()
    if in_flight_job is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            detail={
                "message": "A water report is already being generated for this catchment",
                "job_id": str(in_flight_job.id),
            },
        )

    job = Job(
        type=JobType.CATCHMENT_WATER_REPORT,
        status=JobStatus.PENDING,
        entity_id=catchment_id,
        created_by=current_user.id,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)

    background_tasks.add_task(_run_water_report_job, job_id=job.id, catchment_id=catchment_id)

    return ReportTriggerResponse(job_id=job.id, status="queued")


@router.get("/{catchment_id}/water-reports", response_model=WaterReportDetailResponse)
async def get_latest_water_report(
    catchment_id: UUID,
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> WaterReportDetailResponse:
    """The latest completed water report for a catchment — see the
    module docstring for the full "latest DONE job == latest computed_at
    result pair" correlation rationale. 404, not an empty/partial
    response, whenever no completed report exists yet (never triggered,
    still in flight, or every run so far has failed) or the catchment
    itself is outside the caller's own scope — the same IDOR-safe,
    not-found-vs-forbidden convention `get_catchment` already uses.
    """
    catchment = await db.get(Catchment, catchment_id)
    if catchment is None or catchment.created_by != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Catchment not found")

    job = await db.scalar(
        select(Job)
        .where(
            Job.type == JobType.CATCHMENT_WATER_REPORT,
            Job.entity_id == catchment_id,
            Job.status == JobStatus.DONE,
        )
        .order_by(Job.updated_at.desc())
        .limit(1)
    )
    if job is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No completed water report found for this catchment")

    # computed_at, not period_start/created_at: the only column on either
    # result table that is guaranteed to increase strictly run-over-run
    # (see module docstring) — period_start can repeat across successive
    # same-month reruns since it's derived from the *current* month, not
    # a run-unique value.
    water_balance_result = await db.scalar(
        select(WaterBalanceResult)
        .where(WaterBalanceResult.catchment_id == catchment_id)
        .order_by(WaterBalanceResult.computed_at.desc())
        .limit(1)
    )
    recharge_stress_score = await db.scalar(
        select(RechargeStressScore)
        .where(RechargeStressScore.catchment_id == catchment_id)
        .order_by(RechargeStressScore.computed_at.desc())
        .limit(1)
    )
    if water_balance_result is None or recharge_stress_score is None:
        # A DONE job with no matching result pair would be a genuine
        # data-integrity anomaly (M5-002's _run_water_report_job only
        # ever reaches DONE after generate_water_report() has already
        # persisted both rows) — treated the same as "no completed
        # report" rather than returned as a broken partial response.
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="No completed water report found for this catchment")

    return WaterReportDetailResponse(
        catchment_id=catchment_id,
        generated_at=water_balance_result.computed_at,
        water_balance=WaterBalanceResultResponse.model_validate(water_balance_result),
        recharge_stress=RechargeStressScoreResponse.model_validate(recharge_stress_score),
        job=JobStatusResponse.model_validate(job),
    )


_MAX_HISTORY_LIMIT = 100
_DEFAULT_HISTORY_LIMIT = 24


@router.get("/{catchment_id}/water-reports/history", response_model=list[WaterReportHistoryItem])
async def get_water_report_history(
    catchment_id: UUID,
    limit: int = Query(default=_DEFAULT_HISTORY_LIMIT, ge=1, le=_MAX_HISTORY_LIMIT),
    current_user: AppUser = Depends(require_role(UserRole.PROGRAMME_OFFICER, UserRole.PROGRAMME_ADMIN)),
    db: AsyncSession = Depends(get_db),
) -> list[WaterReportHistoryItem]:
    """Every past completed run for a catchment, most recent first — not
    just the latest one `GET /catchments/{id}/water-reports` returns.

    `WaterBalanceResult` and `RechargeStressScore` are both append-only
    (see their own model docstrings) — every trigger writes new rows,
    nothing is ever overwritten. This endpoint is the first thing that
    reads more than the single latest pair (docs/WELL_Labs_Raichur_Founder_Review_2026.md
    Part 2/5) — no new data, no schema change, purely additive.

    Paired by an exact `computed_at` match, not by ordering-and-zipping
    two separately-limited lists: `water_report_generator.py` computes
    one `computed_at` per run and stamps both sibling rows with it
    (`WaterReportDetailResponse`'s own docstring), so an equality join on
    `(catchment_id, computed_at)` is the true correlation key. Zipping by
    position would silently mispair rows the moment the two tables ever
    drift out of lockstep (e.g. a future partial-failure path that
    persists one row without the other) — this join can't.
    """
    catchment = await db.get(Catchment, catchment_id)
    if catchment is None or catchment.created_by != current_user.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, detail="Catchment not found")

    rows = (
        await db.execute(
            select(WaterBalanceResult, RechargeStressScore)
            .join(
                RechargeStressScore,
                and_(
                    RechargeStressScore.catchment_id == WaterBalanceResult.catchment_id,
                    RechargeStressScore.computed_at == WaterBalanceResult.computed_at,
                ),
            )
            .where(WaterBalanceResult.catchment_id == catchment_id)
            .order_by(WaterBalanceResult.computed_at.desc())
            .limit(limit)
        )
    ).all()

    return [
        WaterReportHistoryItem(
            generated_at=water_balance_result.computed_at,
            water_balance=WaterBalanceResultResponse.model_validate(water_balance_result),
            recharge_stress=RechargeStressScoreResponse.model_validate(recharge_stress_score),
        )
        for water_balance_result, recharge_stress_score in rows
    ]


async def _persist_catchment(
    db: AsyncSession,
    *,
    name: str,
    geometry: GeoJSONMultiPolygon,
    organization_id: UUID | None,
    admin_boundary_id: UUID | None,
    delineation_method: DelineationMethod,
    created_by: UUID,
) -> Catchment:
    """The single persistence path both `POST /catchments` and
    `POST /catchments/upload` call — referenced-id validation,
    duplicate-name scoping, server-side area computation and bounds
    checking, and row construction all live here exactly once.
    """
    if organization_id is not None:
        organization = await db.get(Organization, organization_id)
        if organization is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT, detail="organization_id does not reference a known organization"
            )

    if admin_boundary_id is not None:
        admin_boundary = await db.get(AdminBoundary, admin_boundary_id)
        if admin_boundary is None:
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                detail="admin_boundary_id does not reference a known administrative boundary",
            )

    # Duplicate-name scope: within the same organization if one was
    # given, else among the caller's own catchments — a generic rule
    # that doesn't assume every deployment has organizations populated
    # (Blueprint v2 D8: organization_id is schema-ready, not yet
    # universally required), while still preventing an obviously
    # confusing same-name collision for whoever would actually see both
    # catchments together. Applies identically regardless of which
    # endpoint created the other catchment — a manually-drawn and an
    # uploaded catchment share the same name scope.
    if organization_id is not None:
        duplicate_scope = Catchment.organization_id == organization_id
    else:
        duplicate_scope = and_(Catchment.organization_id.is_(None), Catchment.created_by == created_by)

    duplicate = await db.scalar(select(Catchment).where(Catchment.name == name, duplicate_scope))
    if duplicate is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, detail=f"A catchment named '{name}' already exists in this scope")

    # Unlike FarmPolygon (no DB-level area constraint), Catchment has its
    # own chk_catchment_area CHECK constraint — inserting a placeholder
    # area_ha=0 and updating it after flush (FarmPolygon's own pattern in
    # app/api/farms.py) would violate that constraint the instant the
    # placeholder row is flushed, before the real value is ever computed.
    # Area is therefore computed here against the raw, not-yet-persisted
    # geometry value directly — PostGIS can run ST_Area on any geometry
    # literal, not only a column already written to a table — so the row
    # is only ever constructed with its real, final area_ha.
    geometry_wkb = from_shape(geometry.to_shapely(), srid=4326)
    area_m2 = await db.scalar(select(ST_Area(cast(geometry_wkb, Geography))))
    area_ha = area_m2 / 10_000

    if not (_MIN_CATCHMENT_AREA_HA <= area_ha <= _MAX_CATCHMENT_AREA_HA):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            detail=(
                f"Computed area ({area_ha:.4f} ha) is outside the allowed range "
                f"({_MIN_CATCHMENT_AREA_HA}-{_MAX_CATCHMENT_AREA_HA} ha)"
            ),
        )

    catchment = Catchment(
        organization_id=organization_id,
        name=name,
        geometry=geometry_wkb,
        area_ha=area_ha,
        delineation_method=delineation_method,
        admin_boundary_id=admin_boundary_id,
        resolution_flags=_derive_resolution_flags(area_ha),
        created_by=created_by,
    )
    db.add(catchment)
    await db.commit()
    await db.refresh(catchment)
    return catchment
