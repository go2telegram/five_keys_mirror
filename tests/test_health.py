import asyncio

from aiohttp.test_utils import TestClient, TestServer

from app.health import create_web_app


def test_ping_endpoint_returns_ok_json() -> None:
    async def runner() -> None:
        app = create_web_app()

        async with TestServer(app) as server:
            async with TestClient(server) as client:
                response = await client.get("/ping")
                assert response.status == 200
                data = await response.json()

        assert data["status"] == "ok"
        assert "ts" in data

    asyncio.run(runner())
