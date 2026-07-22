# ─────────────────────────────────────────────────────────────────────────────
# test_health.py — the first test: prove the server boots and /health answers.
# READING ORDER: backend #6  (teaches: FastAPI's TestClient)
#
# WHY test this at all:
#   /health is trivial, but the test does something valuable — it constructs the app
#   (running the startup lifespan and its safety guards) and makes a real request.
#   If an import breaks or a startup check throws, THIS test fails first, fast.
# ─────────────────────────────────────────────────────────────────────────────

from fastapi.testclient import TestClient

from app.main import SERVER_VERSION, app


def test_health_returns_ok() -> None:
    """GET /health should return 200 with status 'ok' and the server version.

    Exists as the smoke test for M0: if this passes, the app object is importable,
    the startup checks pass under the default (safe, mock) config, and routing works.
    """
    # `with TestClient(app)` runs the lifespan startup/shutdown around the block —
    # so this also exercises assert_safe_binding() with the default HOST=127.0.0.1.
    with TestClient(app) as client:
        response = client.get("/health")

    assert response.status_code == 200
    body = response.json()
    assert body["status"] == "ok"
    assert body["version"] == SERVER_VERSION
    # Mock mode is the default, so a fresh config should report mock_llm=true.
    assert body["mock_llm"] is True
