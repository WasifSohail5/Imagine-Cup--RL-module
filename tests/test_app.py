import os
import json
import pytest
from fastapi.testclient import TestClient

os.environ["SQL_CONNECTION_STRING"] = "sqlite+pysqlite:///:memory:"
os.environ["APP_API_KEY"] = "test-key"

import main  # noqa: E402
import quiz  # noqa: E402


@pytest.fixture
def client():
    with TestClient(main.app) as c:
        yield c


def auth_headers():
    return {"X-API-KEY": "test-key"}


def test_health(client):
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["status"] == "ok"


def test_patient_crud(client):
    payload = {
        "full_name": "Alice",
        "dob": "1950-01-01",
        "phone": "123",
        "address": "Somewhere",
    }
    resp = client.post("/patients", json=payload, headers=auth_headers())
    assert resp.status_code == 200
    patient = resp.json()
    resp = client.get("/patients", headers=auth_headers())
    assert any(p["id"] == patient["id"] for p in resp.json())
    resp = client.get(f"/patients/{patient['id']}", headers=auth_headers())
    assert resp.status_code == 200
    assert resp.json()["full_name"] == "Alice"


def test_quiz_flow(client, monkeypatch):
    patient_resp = client.post(
        "/patients",
        json={"full_name": "Bob", "dob": "1940-05-05"},
        headers=auth_headers(),
    )
    patient_id = patient_resp.json()["id"]
    ki_resp = client.post(
        f"/patients/{patient_id}/knowledge",
        json={
            "category": "personal",
            "label": "favorite color",
            "value": "blue",
            "sensitivity_level": 0,
            "is_active": True,
        },
        headers=auth_headers(),
    )
    knowledge_id = ki_resp.json()["id"]

    def fake_generate(**kwargs):
        return [
            {
                "question_type": "recall",
                "prompt": "What is favorite color?",
                "options": None,
                "correct_answer": "blue",
                "item_type": "knowledge",
                "item_id": knowledge_id,
                "difficulty": 1,
                "acceptable_answers": ["blue"],
            }
        ]

    monkeypatch.setattr(quiz, "generate_quiz_questions", fake_generate)

    gen_resp = client.post(
        f"/patients/{patient_id}/quiz/generate",
        headers=auth_headers(),
        params={"n": 1, "reveal_answers": True},
    )
    assert gen_resp.status_code == 200
    data = gen_resp.json()
    session_id = data["session_id"]
    question_id = data["questions"][0]["question_id"]
    submit_resp = client.post(
        f"/quiz/{session_id}/submit",
        headers=auth_headers(),
        json=[
            {
                "question_id": question_id,
                "user_answer": "blue",
                "response_time_ms": 1000,
            }
        ],
    )
    assert submit_resp.status_code == 200
    result = submit_resp.json()
    assert result["score"] == 1.0
