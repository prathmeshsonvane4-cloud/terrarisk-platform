"""One-off loader: ingest an admin-boundary GeoJSON into the admin_boundary
table (Blueprint §05).

Source-agnostic by design (docs/DECISIONS.md, 2026-07-09): swapping the M0
sample fixture for real Bhuvan/ISRO data later means pointing --file at the
new dataset — no code change. Expected GeoJSON feature properties:

    level         "state" | "district" | "taluka" | "village"
    name          boundary name
    parent_level  level of the parent boundary, or null for state
    parent_name   name of the parent boundary, or null for state
    lgd_code      optional Local Government Directory code

Features must be orderable by hierarchy depth (state before district before
taluka before village) so each child's parent already exists when it is
inserted — this script sorts by level for that reason rather than relying
on file order.

Usage:
    python scripts/load_admin_boundaries.py --file scripts/fixtures/sample_admin_boundaries.geojson
"""

import argparse
import asyncio
import json
import sys
from pathlib import Path

# Running this file directly (`python scripts/load_admin_boundaries.py`)
# only puts scripts/ on sys.path, not the backend/ root — without this,
# `from app...` below fails with ModuleNotFoundError. Must run before any
# app.* import.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from geoalchemy2.shape import from_shape
from shapely.geometry import MultiPolygon, Polygon, shape
from sqlalchemy import select, text

from app.database.base import AsyncSessionLocal
from app.models.admin import AdminBoundary
from app.models.enums import BoundaryLevel

_LEVEL_ORDER = {
    BoundaryLevel.STATE: 0,
    BoundaryLevel.DISTRICT: 1,
    BoundaryLevel.TALUKA: 2,
    BoundaryLevel.VILLAGE: 3,
}


def _to_multipolygon(geom) -> MultiPolygon:
    return MultiPolygon([geom]) if isinstance(geom, Polygon) else geom


async def _resolve_parent_id(session, level: BoundaryLevel, name: str) -> object | None:
    if level is None or name is None:
        return None
    result = await session.execute(
        select(AdminBoundary.id).where(AdminBoundary.level == level, AdminBoundary.name == name)
    )
    row = result.scalar_one_or_none()
    if row is None:
        raise ValueError(f"Parent boundary not found: level={level.value} name={name!r} — load parents first")
    return row


async def load(file_path: Path) -> None:
    data = json.loads(file_path.read_text(encoding="utf-8"))
    features = sorted(
        data["features"], key=lambda f: _LEVEL_ORDER[BoundaryLevel(f["properties"]["level"])]
    )

    async with AsyncSessionLocal() as session:
        created, skipped = 0, 0
        for feature in features:
            props = feature["properties"]
            level = BoundaryLevel(props["level"])
            name = props["name"]
            parent_level = BoundaryLevel(props["parent_level"]) if props.get("parent_level") else None
            parent_name = props.get("parent_name")

            existing = await session.execute(
                select(AdminBoundary.id).where(AdminBoundary.level == level, AdminBoundary.name == name)
            )
            if existing.scalar_one_or_none() is not None:
                skipped += 1
                continue

            parent_id = await _resolve_parent_id(session, parent_level, parent_name)
            geom = _to_multipolygon(shape(feature["geometry"]))

            boundary = AdminBoundary(
                level=level,
                name=name,
                parent_id=parent_id,
                lgd_code=props.get("lgd_code"),
                geometry=from_shape(geom, srid=4326),
            )
            session.add(boundary)
            created += 1

        await session.commit()

        # Simplified geometry is a PostGIS computation, not a client-side
        # one, so it stays consistent with however else the app simplifies
        # geometry (Blueprint §05).
        await session.execute(
            text(
                "UPDATE admin_boundary SET geometry_simplified = "
                "ST_SimplifyPreserveTopology(geometry, 0.001) WHERE geometry_simplified IS NULL"
            )
        )
        await session.commit()

    print(f"Loaded {created} boundaries, skipped {skipped} already present.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--file", required=True, type=Path, help="Path to the source GeoJSON file")
    args = parser.parse_args()
    asyncio.run(load(args.file))


if __name__ == "__main__":
    main()
