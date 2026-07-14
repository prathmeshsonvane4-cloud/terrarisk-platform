"""Pure unit tests for app/services/reporting/progress.py's stage
definitions and pipeline-free helpers — no database required, always
runs. The ProgressTracker's DB-backed behavior (the part that actually
matters — does it write and read back correctly under a real pipeline
run) is covered by the integration tests in test_report_generator.py,
consistent with how _set_job_status is only exercised there too, never
in isolation.
"""

from __future__ import annotations

from app.services.reporting.progress import STAGE_DEFINITIONS, STAGE_IDS, initial_progress


def test_stage_definitions_have_unique_non_empty_ids_and_titles():
    assert len(STAGE_IDS) == len(set(STAGE_IDS)), "every stage id must be unique"
    for stage in STAGE_DEFINITIONS:
        assert stage.id, "stage id must not be empty"
        assert stage.title, "stage title must not be empty"


def test_stage_definitions_start_with_preparing_and_end_with_completed():
    # The two bookends the founder's spec explicitly names — asserted
    # here so a future reordering can't silently drop either.
    assert STAGE_DEFINITIONS[0].id == "preparing"
    assert STAGE_DEFINITIONS[-1].id == "completed"


def test_initial_progress_lists_every_stage_pending_with_no_timestamps():
    progress = initial_progress()
    assert [stage["id"] for stage in progress["stages"]] == STAGE_IDS
    for stage in progress["stages"]:
        assert stage["status"] == "pending"
        assert stage["started_at"] is None
        assert stage["completed_at"] is None
        assert stage["metadata"] is None


def test_initial_progress_returns_a_fresh_object_each_call():
    # Mutating one call's result must never leak into the next — this is
    # what lets report_generator.py safely default to initial_progress()
    # inline without a caller having to worry about aliasing.
    first = initial_progress()
    first["stages"][0]["status"] = "running"
    second = initial_progress()
    assert second["stages"][0]["status"] == "pending"
