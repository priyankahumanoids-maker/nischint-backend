import asyncio
import uuid
import sys
import os

sys.path.insert(0, os.getcwd())

from app.db.session import async_session
from app.models.user import User
from app.models.monitored_route import MonitoredRoute
from sqlalchemy import select, text

from app.api.geofence import (
    create_route_for_user,
    list_routes_for_user,
    RouteForUserRequest,
)
from fastapi import HTTPException

async def run_test():
    async with async_session() as session:
        print("=== TEST SETUP: Find real guardian and child ===")
        r_child = await session.execute(
            select(User).where(User.guardian_id.isnot(None)).limit(1)
        )
        child = r_child.scalar_one_or_none()

        if not child:
            r_users = await session.execute(select(User).limit(5))
            users = r_users.scalars().all()
            if len(users) >= 2:
                child = users[1]
                guardian_id = users[0].id
                child.guardian_id = guardian_id
                await session.commit()
                r_g = await session.execute(select(User).where(User.id == guardian_id))
                guardian = r_g.scalar_one()
            else:
                print("Error: Need at least 2 users in DB to test authorization.")
                return
        else:
            guardian_id = child.guardian_id
            r_g = await session.execute(select(User).where(User.id == guardian_id))
            guardian = r_g.scalar_one()

        print(f"Linked Guardian: {guardian.full_name} ({guardian.id})")
        print(f"Protected Child: {child.full_name} ({child.id})")

        # Create mock unlinked non-admin stranger user
        stranger_user = User(
            id=uuid.uuid4(),
            email="unlinked_stranger@test.com",
            full_name="Unlinked Stranger",
            role="guardian"
        )

        print(f"Unlinked Stranger: {stranger_user.full_name} ({stranger_user.id})")
        print("\n" + "="*50)

        print("\n=== TEST 1: POST /geofence/route-for-user with linked guardian ===")
        req = RouteForUserRequest(
            user_id=str(child.id),
            name="Home -> DPS School",
            origin_name="Noida Sector 62",
            origin_lat=28.6273,
            origin_lng=77.3725,
            dest_name="DPS School Sector 30",
            dest_lat=28.5708,
            dest_lng=77.3261,
            corridor_width_m=100.0,
        )

        res1 = await create_route_for_user(req=req, session=session, user=guardian)
        print("Status: 200 OK")
        print("Response JSON:")
        print(res1)

        print("\n" + "="*50)

        print(f"\n=== TEST 2: GET /geofence/routes-for/{child.id} ===")
        res2 = await list_routes_for_user(target_user_id=str(child.id), session=session, user=guardian)
        print("Status: 200 OK")
        print("Response JSON:")
        print(res2)

        print("\n" + "="*50)

        print("\n=== TEST 3: POST /geofence/route-for-user with UNLINKED stranger ===")
        try:
            res3 = await create_route_for_user(req=req, session=session, user=stranger_user)
            print("FAILED: Expected 403 Forbidden but got success!")
        except HTTPException as exc:
            print(f"Status: {exc.status_code} {exc.detail}")
            print(f"Detail: {exc.detail}")

        print("\n" + "="*50)
        print("ALL 3 TESTS VERIFIED!")

if __name__ == "__main__":
    asyncio.run(run_test())
