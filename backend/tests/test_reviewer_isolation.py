from fastapi.testclient import TestClient
from app import config, db
from app.main import app


def test_reviewers_keep_settings_and_triage_separate(monkeypatch):
    monkeypatch.setattr(config, "ISOLATE_REVIEWERS", True)
    first, second = TestClient(app), TestClient(app)
    first.get("/api/settings").raise_for_status()
    second.get("/api/settings").raise_for_status()
    first.post("/api/settings", json={"volume_multiple": 7}).raise_for_status()
    assert first.get("/api/settings").json()["volume_multiple"] == 7
    assert second.get("/api/settings").json()["volume_multiple"] != 7
    first.post("/api/triage", json={"id": "isolation-example", "state": "done"}).raise_for_status()
    a, b = (c.cookies.get("finn_reviewer") for c in (first, second))
    assert db.kv_get("reviewer_triage", a)[0] == {"isolation-example": "done"}
    assert db.kv_get("reviewer_triage", b) is None
