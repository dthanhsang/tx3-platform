"""TX3 Management Server - Seed Data
Creates initial admin user and organization for first-time setup.
Run: python -m database.seed
"""
from __future__ import annotations

import asyncio
import secrets

from sqlalchemy import select

from api.config import settings
from auth import hash_password, hash_token
from database import async_session, init_db
from database.models import License, Organization, ProvisioningToken, Role, User, UserRole


async def seed():
    await init_db()

    async with async_session() as db:
        # Check if already seeded
        existing = await db.execute(select(User).where(User.username == "admin"))
        if existing.scalar_one_or_none():
            print("Database already seeded. Skipping.")
            return

        # Create organization
        org = Organization(name="TX3 Default Organization")
        db.add(org)
        await db.flush()

        # Create admin user
        admin = User(
            username="admin",
            email="admin@tx3.local",
            password_hash=hash_password("admin123"),
            display_name="System Administrator",
            organization_id=org.id,
        )
        db.add(admin)
        await db.flush()

        # Assign owner role
        owner_role = (await db.execute(select(Role).where(Role.name == "owner"))).scalar_one_or_none()
        if owner_role:
            db.add(UserRole(user_id=admin.id, role_id=owner_role.id, scope_type="global"))

        # Create default license
        license_key = f"TX3-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}-{secrets.token_hex(4).upper()}"
        lic = License(
            organization_id=org.id,
            license_key_hash=hash_token(license_key),
            plan="enterprise",
            max_devices=1000,
        )
        db.add(lic)

        # Create provisioning token
        prov_token = secrets.token_urlsafe(32)
        prov = ProvisioningToken(
            organization_id=org.id,
            token_hash=hash_token(prov_token),
            max_uses=10000,
        )
        db.add(prov)

        await db.commit()

        print("=" * 60)
        print("TX3 Management Server - Initial Setup")
        print("=" * 60)
        print(f"Admin Username:     admin")
        print(f"Admin Password:     admin123")
        print(f"License Key:        {license_key}")
        print(f"Provisioning Token: {prov_token}")
        print(f"Organization:       {org.name} ({org.id})")
        print("=" * 60)
        print("⚠ CHANGE THE ADMIN PASSWORD IMMEDIATELY!")
        print("⚠ Save the License Key and Provisioning Token securely.")
        print("=" * 60)


if __name__ == "__main__":
    asyncio.run(seed())
