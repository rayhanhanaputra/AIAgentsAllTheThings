"""Bounded out-of-band observers for physical hardware assessment runs."""

from __future__ import annotations

import base64
import http.client
import json
import ssl
from dataclasses import asdict, dataclass
from typing import Any, Dict, Optional
from urllib.parse import urlsplit

from .connectors import (
    ConnectorError,
    MAX_HTTP_RESPONSE_BYTES,
    _PinnedHTTPConnection,
    _PinnedHTTPSConnection,
    _resolve_destination,
)
from .targets import TargetProfile

MAX_SCREENSHOT_BYTES = 5 * 1024 * 1024


@dataclass(frozen=True)
class Observation:
    kind: str
    phase: str
    source: str
    text: str
    raw: str
    metadata: Dict[str, Any]
    screenshot_data_url: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def capture_observation(profile: TargetProfile, phase: str) -> Observation:
    if profile.observer_kind == "http":
        return _capture_http(profile, phase)
    if profile.observer_kind == "browser":
        return _capture_browser(profile, phase)
    raise ConnectorError("out-of-band observer is not configured")


def _capture_http(profile: TargetProfile, phase: str) -> Observation:
    if not profile.observer_url:
        raise ConnectorError("HTTP observer URL is missing")
    parsed = urlsplit(profile.observer_url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    pinned_ip = _resolve_destination(parsed.hostname or "", port, public_allowed=True)
    connection_type = (
        _PinnedHTTPSConnection if parsed.scheme == "https" else _PinnedHTTPConnection
    )
    connection = connection_type(
        parsed.hostname or "", pinned_ip, port, profile.observer_timeout_seconds
    )
    path = parsed.path or "/"
    if parsed.query:
        path += "?" + parsed.query
    try:
        connection.request("GET", path, headers={"Accept": "application/json, text/plain"})
        response = connection.getresponse()
        if 300 <= response.status < 400:
            raise ConnectorError("observer redirects are not followed")
        payload = response.read(MAX_HTTP_RESPONSE_BYTES + 1)
        if len(payload) > MAX_HTTP_RESPONSE_BYTES:
            raise ConnectorError("observer response exceeds 1 MiB")
        raw = payload.decode("utf-8", errors="replace")
        text = _text_from_http_payload(raw)
        metadata = {
            "status": response.status,
            "reason": response.reason,
            "content_type": response.getheader("Content-Type"),
        }
    except ConnectorError:
        raise
    except (OSError, http.client.HTTPException, ssl.SSLError) as exc:
        raise ConnectorError(f"HTTP observer connection failed: {exc}") from exc
    finally:
        connection.close()
    return Observation(
        kind="http",
        phase=phase,
        source=profile.observer_url,
        text=text,
        raw=raw,
        metadata=metadata,
    )


def _text_from_http_payload(raw: str) -> str:
    try:
        decoded = json.loads(raw)
    except json.JSONDecodeError:
        return raw
    if isinstance(decoded, dict):
        for key in ("text", "message", "response", "status"):
            value = decoded.get(key)
            if isinstance(value, str):
                return value
    return json.dumps(decoded, ensure_ascii=False)


def _capture_browser(profile: TargetProfile, phase: str) -> Observation:
    if not profile.observer_url or not profile.observer_selector:
        raise ConnectorError("browser observer URL or selector is missing")
    _validate_browser_destination(profile.observer_url)
    try:
        from playwright.sync_api import Error as PlaywrightError
        from playwright.sync_api import sync_playwright
    except ImportError as exc:
        raise ConnectorError(
            "browser observation requires the 'hardware' Python extra and Chromium"
        ) from exc

    try:
        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            context = None
            try:
                context = browser.new_context(
                    accept_downloads=False,
                    service_workers="block",
                    viewport={"width": 1440, "height": 900},
                )
                expected_origin = _origin(profile.observer_url)

                def guard_request(route: Any) -> None:
                    request_url = route.request.url
                    if request_url.startswith(("data:", "blob:")):
                        route.continue_()
                        return
                    try:
                        allowed = _origin(request_url) == expected_origin
                    except (TypeError, ValueError):
                        allowed = False
                    if allowed:
                        route.continue_()
                    else:
                        route.abort("blockedbyclient")

                context.route("**/*", guard_request)
                page = context.new_page()
                page.goto(
                    profile.observer_url,
                    wait_until="domcontentloaded",
                    timeout=int(profile.observer_timeout_seconds * 1_000),
                )
                if _origin(page.url) != expected_origin:
                    raise ConnectorError("browser observer navigation changed origin")
                locator = page.locator(profile.observer_selector).first
                locator.wait_for(
                    state="visible",
                    timeout=int(profile.observer_timeout_seconds * 1_000),
                )
                if _origin(page.url) != expected_origin:
                    raise ConnectorError("browser observer navigation changed origin")
                text = locator.inner_text(
                    timeout=int(profile.observer_timeout_seconds * 1_000)
                )
                screenshot_url = None
                if profile.observer_capture_screenshot:
                    screenshot = page.screenshot(type="png", full_page=True)
                    if len(screenshot) > MAX_SCREENSHOT_BYTES:
                        raise ConnectorError("browser observer screenshot exceeds 5 MiB")
                    screenshot_url = "data:image/png;base64," + base64.b64encode(
                        screenshot
                    ).decode()
                metadata = {"page_title": page.title(), "final_url": page.url}
            finally:
                if context is not None:
                    context.close()
                browser.close()
    except ConnectorError:
        raise
    except PlaywrightError as exc:
        raise ConnectorError(f"browser observer failed: {exc}") from exc
    return Observation(
        kind="browser",
        phase=phase,
        source=profile.observer_url,
        text=text[:MAX_HTTP_RESPONSE_BYTES],
        raw=json.dumps({"text": text[:MAX_HTTP_RESPONSE_BYTES]}, ensure_ascii=False),
        metadata=metadata,
        screenshot_data_url=screenshot_url,
    )


def _validate_browser_destination(url: str) -> None:
    parsed = urlsplit(url)
    port = parsed.port or (443 if parsed.scheme == "https" else 80)
    _resolve_destination(parsed.hostname or "", port, public_allowed=True)


def _origin(url: str) -> tuple[str, str, int]:
    parsed = urlsplit(url)
    return (
        parsed.scheme,
        parsed.hostname or "",
        parsed.port or (443 if parsed.scheme == "https" else 80),
    )
