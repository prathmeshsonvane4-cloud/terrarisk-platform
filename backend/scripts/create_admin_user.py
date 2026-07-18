"""One-off CLI: create an AppUser (bank-side login).

Every other row-seeding script in this directory (seed_default_config_weight.py,
load_admin_boundaries.py) has a way to provision itself without a running
API — this is the missing one for app_user. There is no registration
endpoint and no admin-creation endpoint anywhere in the API (auth.py only
has /login and /refresh, deliberately: Blueprint/Product Design v2 describe
a small, fixed set of named DCCB Latur officer accounts, not self-service
signup). Without this script a fresh deployment has a working API and an
empty app_user table with no way to log in — this is what M3's
"create first admin/officer" setup step actually runs.

Usage:
    python scripts/create_admin_user.py --email officer@dccblatur.example \\
        --password "a-real-password" --full-name "First Officer" --role branch_manager

    python scripts/create_admin_user.py --list-roles
"""

from __future__ import annotations

import argparse
import asyncio
import sys
import uuid
from pathlib import Path

# Running this file directly (`python scripts/create_admin_user.py`) only
# puts scripts/ on sys.path, not the backend/ root — without this,
# `from app...` below fails with ModuleNotFoundError. Must run before any
# app.* import (same fix as seed_default_config_weight.py).
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import select

from app.core.security import hash_password
from app.database.base import AsyncSessionLocal
from app.models.enums import UserRole
from app.models.user import AppUser


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create a TerraRisk app_user login (first admin/officer setup).")
    parser.add_argument("--email", help="Login email — must be unique.")
    parser.add_argument("--password", help="Plain-text password (hashed with bcrypt before storage, never logged).")
    parser.add_argument("--full-name", help="Officer's display name.")
    parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        help="One of: " + ", ".join(role.value for role in UserRole),
    )
    parser.add_argument(
        "--branch-id",
        type=uuid.UUID,
        default=None,
        help="Optional branch UUID (app_user.branch_id) — scopes owner-or-branch access checks. "
        "Omit for roles (e.g. ceo/chairman) that aren't branch-scoped.",
    )
    parser.add_argument(
        "--list-roles",
        action="store_true",
        help="Print the valid --role values and exit, without creating a user.",
    )
    return parser.parse_args()


async def create_user(*, email: str, password: str, full_name: str, role: str, branch_id: uuid.UUID | None) -> None:
    async with AsyncSessionLocal() as db:
        existing = (await db.execute(select(AppUser).where(AppUser.email == email))).scalar_one_or_none()
        if existing is not None:
            print(f"A user with email '{email}' already exists ({existing.id}) — not creating a duplicate.")
            return

        user = AppUser(
            email=email,
            password_hash=hash_password(password),
            full_name=full_name,
            role=UserRole(role),
            branch_id=branch_id,
            is_active=True,
        )
        db.add(user)
        await db.commit()
        await db.refresh(user)
        print(f"Created user {user.email} ({user.role.value}), id={user.id}")


def main() -> None:
    args = _parse_args()

    if args.list_roles:
        for role in UserRole:
            print(role.value)
        return

    missing = [
        flag
        for flag, value in (("--email", args.email), ("--password", args.password), ("--full-name", args.full_name), ("--role", args.role))
        if not value
    ]
    if missing:
        print(f"Missing required argument(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)

    asyncio.run(
        create_user(
            email=args.email,
            password=args.password,
            full_name=args.full_name,
            role=args.role,
            branch_id=args.branch_id,
        )
    )


if __name__ == "__main__":
    main()
