"""One-off CLI: create or reset an AppUser (bank-side login).

Every other row-seeding script in this directory (seed_default_config_weight.py,
load_admin_boundaries.py) has a way to provision itself without a running
API — this is the missing one for app_user. There is no registration
endpoint and no admin-creation endpoint anywhere in the API (auth.py only
has /login and /refresh, deliberately: Blueprint/Product Design v2 describe
a small, fixed set of named pilot-bank officer accounts, not self-service
signup). Without this script a fresh deployment has a working API and an
empty app_user table with no way to log in — this is what M3's
"create first admin/officer" setup step actually runs.

--reset-password (RC2 security audit finding): the create path originally
had no companion way to rotate a credential for an *existing* account — if
an officer's password was compromised, forgotten, or simply due for
routine rotation, the only path was direct database surgery. This mirrors
create_user()'s exact pattern for an existing row instead of a new one.

Usage:
    python scripts/create_admin_user.py --email officer@dccblatur.example \\
        --password "a-real-password" --full-name "First Officer" --role branch_manager

    python scripts/create_admin_user.py --reset-password \\
        --email officer@dccblatur.example --password "a-new-real-password"

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

# Length-based, not complexity-rule-based (current NIST guidance: length is
# the strongest predictor of resistance to guessing, and composition rules
# mostly push users toward predictable substitutions). This is the only
# account-provisioning path in the system — RC2 audit finding.
_MIN_PASSWORD_LENGTH = 12


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Create or reset a TerraRisk app_user login.")
    parser.add_argument("--email", help="Login email — must be unique when creating.")
    parser.add_argument("--password", help="Plain-text password (hashed with bcrypt before storage, never logged).")
    parser.add_argument("--full-name", help="Officer's display name (create only).")
    parser.add_argument(
        "--role",
        choices=[role.value for role in UserRole],
        help="One of: " + ", ".join(role.value for role in UserRole) + " (create only).",
    )
    parser.add_argument(
        "--branch-id",
        type=uuid.UUID,
        default=None,
        help="Optional branch UUID (app_user.branch_id) — scopes owner-or-branch access checks. "
        "Omit for roles (e.g. ceo/chairman) that aren't branch-scoped. (create only)",
    )
    parser.add_argument(
        "--reset-password",
        action="store_true",
        help="Rotate the password for an existing --email instead of creating a new user. "
        "--full-name/--role/--branch-id are ignored in this mode.",
    )
    parser.add_argument(
        "--list-roles",
        action="store_true",
        help="Print the valid --role values and exit, without creating a user.",
    )
    return parser.parse_args()


def _validate_password(password: str) -> None:
    if len(password) < _MIN_PASSWORD_LENGTH:
        print(f"--password must be at least {_MIN_PASSWORD_LENGTH} characters.", file=sys.stderr)
        sys.exit(2)


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


async def reset_password(*, email: str, password: str) -> None:
    async with AsyncSessionLocal() as db:
        user = (await db.execute(select(AppUser).where(AppUser.email == email))).scalar_one_or_none()
        if user is None:
            print(f"No user with email '{email}' exists — nothing to reset.", file=sys.stderr)
            sys.exit(1)

        user.password_hash = hash_password(password)
        await db.commit()
        print(f"Password reset for {user.email} (id={user.id}).")


def main() -> None:
    args = _parse_args()

    if args.list_roles:
        for role in UserRole:
            print(role.value)
        return

    if args.reset_password:
        missing = [flag for flag, value in (("--email", args.email), ("--password", args.password)) if not value]
        if missing:
            print(f"Missing required argument(s): {', '.join(missing)}", file=sys.stderr)
            sys.exit(2)
        _validate_password(args.password)
        asyncio.run(reset_password(email=args.email, password=args.password))
        return

    missing = [
        flag
        for flag, value in (("--email", args.email), ("--password", args.password), ("--full-name", args.full_name), ("--role", args.role))
        if not value
    ]
    if missing:
        print(f"Missing required argument(s): {', '.join(missing)}", file=sys.stderr)
        sys.exit(2)
    _validate_password(args.password)

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
