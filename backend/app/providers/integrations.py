from __future__ import annotations

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta
from typing import Protocol
from urllib.parse import urlencode, urlparse

import httpx
from cryptography.fernet import Fernet, InvalidToken

from app.core.config import Settings
from app.core.errors import ApiError
from app.core.ids import new_id
from app.core.time import utc_now


def _hostname_allowed(url: str, allowed_domains: list[str]) -> bool:
    hostname = (urlparse(url).hostname or "").lower().rstrip(".")
    return any(
        hostname == domain.lower().rstrip(".")
        or hostname.endswith("." + domain.lower().rstrip("."))
        for domain in allowed_domains
    )


def _collect_sources(value: object) -> list[dict[str, object]]:
    found: list[dict[str, object]] = []
    if isinstance(value, dict):
        url = value.get("url")
        if isinstance(url, str) and url.startswith(("https://", "http://")):
            title = value.get("title")
            text = value.get("text", value.get("snippet", ""))
            found.append(
                {
                    "url": url,
                    "title": str(title or url)[:300],
                    "excerpt": str(text or "")[:2000],
                }
            )
        for item in value.values():
            found.extend(_collect_sources(item))
    elif isinstance(value, list):
        for item in value:
            found.extend(_collect_sources(item))
    return found


class OfficialSearchProvider(Protocol):
    name: str

    def search(
        self, query: str, allowed_domains: list[str]
    ) -> tuple[list[dict[str, object]], str]: ...


class MockOfficialSearchProvider:
    name = "mock"

    def search(self, query: str, allowed_domains: list[str]) -> tuple[list[dict[str, object]], str]:
        domain = allowed_domains[0]
        return (
            [
                {
                    "id": new_id("off"),
                    "institution": domain,
                    "title": f"{query}（官方资料）",
                    "url": f"https://{domain}/search-result",
                    "excerpt": "这是受白名单约束的模拟官方资料摘要。",
                    "published_at": None,
                    "accessed_at": utc_now().isoformat(),
                    "content_hash": hashlib.sha256(query.encode()).hexdigest(),
                }
            ],
            "mock-official-search-v1",
        )


class VolcengineOfficialSearchProvider:
    name = "volcengine"

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def search(self, query: str, allowed_domains: list[str]) -> tuple[list[dict[str, object]], str]:
        key = self.settings.official_search_api_key.get_secret_value()
        if not key or not self.settings.official_search_model_id:
            raise ApiError("OFFICIAL_SEARCH_UNAVAILABLE", "官方联网搜索尚未配置。", status_code=503)
        domain_clause = " OR ".join(f"site:{item}" for item in allowed_domains)
        payload = {
            "model": self.settings.official_search_model_id,
            "store": False,
            "input": (
                "只搜索并返回以下官方域名中的资料；不要使用其他域名："
                f"{', '.join(allowed_domains)}。查询：{query}。检索约束：{domain_clause}"
            ),
            "tools": [{"type": "web_search"}],
        }
        try:
            response = httpx.post(
                self.settings.official_search_base_url.rstrip("/") + "/responses",
                headers={"Authorization": f"Bearer {key}"},
                json=payload,
                timeout=self.settings.official_search_timeout_seconds,
            )
            response.raise_for_status()
            raw = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(
                "OFFICIAL_SEARCH_UNAVAILABLE", "官方联网搜索暂时不可用。", status_code=503
            ) from exc
        candidates = _collect_sources(raw)
        unique: dict[str, dict[str, object]] = {}
        for item in candidates:
            url = str(item["url"])
            if not _hostname_allowed(url, allowed_domains):
                continue
            item.update(
                {
                    "id": new_id("off"),
                    "institution": urlparse(url).hostname or "official",
                    "published_at": None,
                    "accessed_at": utc_now().isoformat(),
                    "content_hash": hashlib.sha256(
                        json.dumps(item, sort_keys=True, ensure_ascii=False).encode()
                    ).hexdigest(),
                }
            )
            unique[url] = item
        if not unique:
            raise ApiError(
                "OFFICIAL_SOURCE_NOT_FOUND",
                "没有找到符合当前官方白名单的来源，已停止而不会扩大搜索范围。",
                status_code=422,
            )
        returned_model = str(raw.get("model", self.settings.official_search_model_id))
        return list(unique.values())[:8], returned_model


def build_official_search_provider(settings: Settings) -> OfficialSearchProvider:
    if settings.official_search_provider == "mock":
        return MockOfficialSearchProvider()
    if settings.official_search_provider == "volcengine":
        return VolcengineOfficialSearchProvider(settings)
    raise ApiError(
        "OFFICIAL_POLICY_UNAVAILABLE", "尚未配置官方域名白名单与联网搜索。", status_code=409
    )


def deliver_notification_webhook(settings: Settings, payload: dict[str, object]) -> str:
    """Deliver a reminder without placing its private payload in logs or audit metadata."""

    if settings.notification_provider == "mock":
        return new_id("mock_notification")
    if settings.notification_provider != "webhook":
        raise ApiError(
            "NOTIFICATION_PROVIDER_UNAVAILABLE", "通知投递服务尚未配置。", status_code=409
        )
    body = json.dumps(payload, ensure_ascii=False, separators=(",", ":")).encode()
    signature = hmac.new(
        settings.notification_webhook_secret.get_secret_value().encode(),
        body,
        hashlib.sha256,
    ).hexdigest()
    try:
        response = httpx.post(
            settings.notification_webhook_url,
            content=body,
            headers={
                "Content-Type": "application/json",
                "X-Benren-Signature": f"sha256={signature}",
            },
            timeout=settings.notification_timeout_seconds,
        )
        response.raise_for_status()
    except httpx.HTTPError as exc:
        raise ApiError(
            "NOTIFICATION_DELIVERY_FAILED", "通知投递失败，将按策略重试。", status_code=503
        ) from exc
    receipt = response.headers.get("X-Request-Id") or response.headers.get("X-Message-Id")
    return receipt or stable_notification_receipt(body)


def stable_notification_receipt(body: bytes) -> str:
    return "webhook-" + hashlib.sha256(body).hexdigest()[:24]


class TokenCodec:
    def __init__(self, signing_key: str) -> None:
        key = base64.urlsafe_b64encode(hashlib.sha256(signing_key.encode()).digest())
        self.fernet = Fernet(key)

    def encrypt(self, value: dict[str, object]) -> dict[str, object]:
        token = self.fernet.encrypt(json.dumps(value, ensure_ascii=False).encode()).decode()
        return {"ciphertext": token, "version": 1}

    def decrypt(self, value: dict[str, object]) -> dict[str, object]:
        token = value.get("ciphertext")
        if not isinstance(token, str):
            raise ApiError("CALENDAR_AUTH_INVALID", "第三方日历授权已失效。", status_code=409)
        try:
            decoded = json.loads(self.fernet.decrypt(token.encode()).decode())
        except (InvalidToken, ValueError, TypeError, json.JSONDecodeError) as exc:
            raise ApiError(
                "CALENDAR_AUTH_INVALID", "第三方日历授权已失效。", status_code=409
            ) from exc
        if not isinstance(decoded, dict):
            raise ApiError("CALENDAR_AUTH_INVALID", "第三方日历授权已失效。", status_code=409)
        return decoded


class CalendarProvider:
    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    def authorization_url(self, state: str) -> str:
        if self.settings.external_calendar_provider == "mock":
            return f"{self.settings.api_base_url}/mock-calendar/authorize?state={state}"
        if self.settings.external_calendar_provider != "generic_oauth":
            raise ApiError("CALENDAR_PROVIDER_UNAVAILABLE", "第三方日历尚未配置。", status_code=409)
        return (
            self.settings.external_calendar_authorize_url
            + "?"
            + urlencode(
                {
                    "response_type": "code",
                    "client_id": self.settings.external_calendar_client_id,
                    "redirect_uri": self.settings.external_calendar_redirect_uri,
                    "scope": " ".join(self.settings.external_calendar_scopes),
                    "state": state,
                }
            )
        )

    def exchange_code(self, code: str) -> tuple[dict[str, object], str | None, datetime | None]:
        if self.settings.external_calendar_provider == "mock":
            return (
                {"access_token": f"mock-{code}", "token_type": "Bearer"},
                "mock-calendar-user",
                utc_now() + timedelta(hours=1),
            )
        try:
            response = httpx.post(
                self.settings.external_calendar_token_url,
                data={
                    "grant_type": "authorization_code",
                    "code": code,
                    "client_id": self.settings.external_calendar_client_id,
                    "client_secret": (
                        self.settings.external_calendar_client_secret.get_secret_value()
                    ),
                    "redirect_uri": self.settings.external_calendar_redirect_uri,
                },
                timeout=self.settings.external_calendar_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError("CALENDAR_AUTH_FAILED", "第三方日历授权失败。", status_code=502) from exc
        if not isinstance(payload, dict) or not payload.get("access_token"):
            raise ApiError("CALENDAR_AUTH_FAILED", "第三方日历没有返回有效授权。", status_code=502)
        expires_in = payload.get("expires_in")
        expires = (
            utc_now() + timedelta(seconds=int(expires_in))
            if isinstance(expires_in, int | float)
            else None
        )
        return payload, str(payload.get("account_id") or "") or None, expires

    def _headers(self, tokens: dict[str, object]) -> dict[str, str]:
        access = tokens.get("access_token")
        if not isinstance(access, str) or not access:
            raise ApiError("CALENDAR_AUTH_INVALID", "第三方日历授权已失效。", status_code=409)
        return {"Authorization": f"Bearer {access}", "Content-Type": "application/json"}

    def upsert_event(
        self, tokens: dict[str, object], event: dict[str, object], external_id: str | None = None
    ) -> tuple[str, str | None]:
        if self.settings.external_calendar_provider == "mock":
            return external_id or new_id("mockevt"), "mock-v1"
        url = self.settings.external_calendar_events_url.rstrip("/")
        try:
            response = (
                httpx.put(
                    f"{url}/{external_id}",
                    headers=self._headers(tokens),
                    json=event,
                    timeout=self.settings.external_calendar_timeout_seconds,
                )
                if external_id
                else httpx.post(
                    url,
                    headers=self._headers(tokens),
                    json=event,
                    timeout=self.settings.external_calendar_timeout_seconds,
                )
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(
                "CALENDAR_SYNC_FAILED", "第三方日历写入失败，可稍后重试。", status_code=503
            ) from exc
        event_id = payload.get("id") if isinstance(payload, dict) else None
        if not isinstance(event_id, str) or not event_id:
            raise ApiError("CALENDAR_SYNC_FAILED", "第三方日历未返回事件编号。", status_code=502)
        version = payload.get("etag") if isinstance(payload, dict) else None
        return event_id, str(version) if version else None

    def delete_event(self, tokens: dict[str, object], external_id: str) -> None:
        if self.settings.external_calendar_provider == "mock":
            return
        try:
            response = httpx.delete(
                self.settings.external_calendar_events_url.rstrip("/") + f"/{external_id}",
                headers=self._headers(tokens),
                timeout=self.settings.external_calendar_timeout_seconds,
            )
            if response.status_code != 404:
                response.raise_for_status()
        except httpx.HTTPError as exc:
            raise ApiError(
                "CALENDAR_SYNC_FAILED", "第三方日历撤销失败，可稍后重试。", status_code=503
            ) from exc

    def get_event(self, tokens: dict[str, object], external_id: str) -> dict[str, object]:
        if self.settings.external_calendar_provider == "mock":
            return {"id": external_id, "unchanged": True}
        try:
            response = httpx.get(
                self.settings.external_calendar_events_url.rstrip("/") + f"/{external_id}",
                headers=self._headers(tokens),
                timeout=self.settings.external_calendar_timeout_seconds,
            )
            response.raise_for_status()
            payload = response.json()
        except (httpx.HTTPError, ValueError) as exc:
            raise ApiError(
                "CALENDAR_SYNC_FAILED", "第三方日历读取失败，可稍后重试。", status_code=503
            ) from exc
        if not isinstance(payload, dict):
            raise ApiError("CALENDAR_SYNC_FAILED", "第三方日历返回格式不正确。", status_code=502)
        allowed = {"title", "start_at", "end_at", "timezone", "status", "etag", "id"}
        return {str(key): value for key, value in payload.items() if key in allowed}


def launch_sft_job(settings: Settings, payload: dict[str, object]) -> str:
    if settings.sft_provider == "mock":
        return new_id("mock_sft_job")
    if settings.sft_provider != "volcengine":
        raise ApiError("SFT_PROVIDER_UNAVAILABLE", "SFT 训练服务尚未配置。", status_code=409)
    try:
        response = httpx.post(
            settings.sft_base_url.rstrip("/") + settings.sft_launch_path,
            headers={"Authorization": f"Bearer {settings.sft_api_key.get_secret_value()}"},
            json=payload,
            timeout=60,
        )
        response.raise_for_status()
        raw = response.json()
    except (httpx.HTTPError, ValueError) as exc:
        raise ApiError("SFT_LAUNCH_FAILED", "SFT 训练任务创建失败。", status_code=503) from exc
    job_id = raw.get("id") if isinstance(raw, dict) else None
    if not isinstance(job_id, str) or not job_id:
        raise ApiError("SFT_LAUNCH_FAILED", "SFT 服务未返回训练任务编号。", status_code=502)
    return job_id
