from __future__ import annotations

from collections.abc import Callable
from concurrent.futures import ThreadPoolExecutor
from datetime import timedelta

from fastapi.testclient import TestClient

from app.core.config import Settings
from app.core.security import timed_invite_record
from app.core.time import utc_now
from tests.conftest import INVITE_A, INVITE_B, create_course


def test_invalid_invite_uses_unified_error(client: TestClient) -> None:
    response = client.post("/api/v1/auth/invite-session", json={"invite_code": "wrong-code"})
    assert response.status_code == 401
    body = response.json()["error"]
    assert body["code"] == "INVALID_INVITE"
    assert body["request_id"].startswith("req_")
    assert "wrong-code" not in response.text


def test_unexpired_timed_invite_can_login(
    client: TestClient, test_settings: Settings
) -> None:
    invite = "temporary-invite-code"
    test_settings.timed_invite_code_hashes = [
        timed_invite_record(invite, utc_now() + timedelta(minutes=5))
    ]

    response = client.post("/api/v1/auth/invite-session", json={"invite_code": invite})

    assert response.status_code == 200


def test_expired_timed_invite_is_rejected(
    client: TestClient, test_settings: Settings
) -> None:
    invite = "expired-temporary-code"
    test_settings.timed_invite_code_hashes = [
        timed_invite_record(invite, utc_now() - timedelta(seconds=1))
    ]

    response = client.post("/api/v1/auth/invite-session", json={"invite_code": invite})

    assert response.status_code == 401
    assert response.json()["error"]["code"] == "INVALID_INVITE"


def test_same_invite_returns_same_user(
    client: TestClient, login: Callable[[TestClient, str], None]
) -> None:
    login(client, INVITE_A)
    first = client.get("/api/v1/me").json()["id"]
    client.cookies.clear()
    login(client, INVITE_A)
    second = client.get("/api/v1/me").json()["id"]
    assert first == second


def test_same_invite_can_be_redeemed_concurrently(client: TestClient) -> None:
    def redeem() -> tuple[int, str]:
        with TestClient(client.app) as concurrent_client:
            response = concurrent_client.post(
                "/api/v1/auth/invite-session", json={"invite_code": INVITE_A}
            )
            return response.status_code, response.json().get("user", {}).get("id", "")

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: redeem(), range(2)))

    assert {status for status, _ in results} == {200}
    assert len({user_id for _, user_id in results}) == 1


def test_course_create_is_idempotent(
    client: TestClient, login: Callable[[TestClient, str], None]
) -> None:
    login(client, INVITE_A)
    first = create_course(client, "same-course-key")
    second = create_course(client, "same-course-key")
    assert first["id"] == second["id"]


def test_idempotency_key_reuse_with_different_body_is_rejected(
    client: TestClient, login: Callable[[TestClient, str], None]
) -> None:
    login(client, INVITE_A)
    headers = {"Idempotency-Key": "course-conflict-key"}
    assert client.post("/api/v1/courses", json={}, headers=headers).status_code == 201
    response = client.post("/api/v1/courses", json={"temporary_title": "物理"}, headers=headers)
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "IDEMPOTENCY_CONFLICT"


def test_course_acl_does_not_leak_content(
    client: TestClient, login: Callable[[TestClient, str], None]
) -> None:
    login(client, INVITE_A)
    course = create_course(client)
    client.cookies.clear()
    login(client, INVITE_B)
    response = client.get(f"/api/v1/courses/{course['id']}")
    assert response.status_code == 403
    assert response.json()["error"]["code"] == "FORBIDDEN"
