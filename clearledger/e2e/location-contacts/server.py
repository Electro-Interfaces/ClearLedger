"""Только тестовый HTTP-сервер: фальшивые записи, отдельная contacts_test, loopback."""
import asyncio
import os
import sys
from pathlib import Path


def main():
    os.environ["DATABASE_URL"] = os.environ["TEST_DATABASE_URL"]
    server = Path(__file__).resolve().parents[2] / "server"
    sys.path[:0] = [str(server / "tests"), str(server)]
    from test_location_contacts_integration import LocationContactsIntegration, RUN
    if not RUN:
        raise RuntimeError("Нужна отдельная локальная PostgreSQL contacts_test")
    LocationContactsIntegration.setUpClass()
    case = LocationContactsIntegration()
    asyncio.run(case.asyncSetUp())
    asyncio.run(case.client.aclose())
    app = case.app

    @app.post("/api/__test/reset")
    async def reset():
        await case.asyncSetUp()
        await case.client.aclose()
        return {"status": "reset"}

    @app.post("/api/__test/scoped")
    async def scoped():
        await case.restrict()
        return {"status": "scoped"}

    import uvicorn
    uvicorn.run(app, host="127.0.0.1", port=18538, log_level="warning")


if __name__ == "__main__":
    main()
