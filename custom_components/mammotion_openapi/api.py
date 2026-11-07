"""Async client for the documented Mammotion Open API.

The caller owns the aiohttp session. Never log response bodies or credentials.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from email.utils import parsedate_to_datetime
from time import monotonic
from typing import Any
from urllib.parse import quote

import aiohttp
from aiohttp.http_exceptions import LineTooLong

from .const import ACTIONS, API_URL, PROPERTIES, TOKEN_URL

MAX_SSE_SIZE = 1_000_000


class MammotionError(Exception):
    """API or transport failure with a safe, credential-free message."""


class AuthenticationError(MammotionError):
    """Credentials were rejected."""


class RateLimitError(MammotionError):
    """The server requested a cooldown."""


class StreamPreempted(MammotionError):
    """Another SSE client took over; automatic reconnection must stop."""


def object_data(data: Any) -> dict[str, Any]:
    """Accept the object schema and the singleton array in the getting-started guide."""
    if isinstance(data, list) and len(data) == 1:
        data = data[0]
    if not isinstance(data, dict):
        raise MammotionError("Unexpected object response from Mammotion")
    return data


async def sse_messages(content: aiohttp.StreamReader) -> AsyncIterator[dict[str, Any]]:
    """Parse SSE lines, comments and multiline data without depending on TCP chunks."""
    parts: list[str] = []
    size = 0
    try:
        async for raw in content:
            line = raw.decode("utf-8-sig").rstrip("\r\n")
            if not line:
                if parts:
                    try:
                        payload = json.loads("\n".join(parts))
                    except ValueError:
                        payload = None  # Plain-text initialization and heartbeat messages.
                    if isinstance(payload, dict):
                        if payload.get("pushTag") == "sc" and str(payload.get("pushType")) == "1":
                            raise StreamPreempted(
                                "Another client took over the Mammotion SSE connection"
                            )
                        yield payload
                parts = []
                size = 0
            elif line.startswith("data:"):
                value = line[5:].removeprefix(" ")
                size += len(raw)
                if size > MAX_SSE_SIZE:
                    raise MammotionError("Mammotion SSE message exceeded size limit")
                parts.append(value)
    except LineTooLong, ValueError, UnicodeError:
        # aiohttp's line-limit exceptions may include payload excerpts. Never chain them.
        raise MammotionError("Invalid or oversized Mammotion SSE message") from None


class MammotionClient:
    """Token caching, bounded requests and all seven documented REST operations."""

    def __init__(self, session: aiohttp.ClientSession, client_id: str, client_secret: str) -> None:
        self.session = session
        self.client_id = client_id
        self._secret = client_secret
        self._token: str | None = None
        self._expires = 0.0
        self._token_lock = asyncio.Lock()
        self._cooldown = 0.0

    def _check_cooldown(self) -> None:
        if monotonic() < self._cooldown:
            raise RateLimitError("Mammotion API cooldown is active; try again later")

    def _check_status(self, response: aiohttp.ClientResponse, *, token: bool = False) -> None:
        if response.status == 429:
            retry_after = response.headers.get("Retry-After", "60")
            try:
                delay = float(retry_after)
            except ValueError:
                try:
                    delay = (parsedate_to_datetime(retry_after) - datetime.now(UTC)).total_seconds()
                except ValueError, TypeError, OverflowError:
                    delay = 60
            self._cooldown = monotonic() + max(1, min(delay, 86400))
            raise RateLimitError("Mammotion rate limit reached; waiting before further requests")
        if response.status in (401, 403) or (token and response.status == 400):
            raise AuthenticationError("Mammotion rejected the API credentials or permissions")
        if response.status >= 400:
            raise MammotionError(f"Mammotion returned HTTP {response.status}")

    async def access_token(self) -> str:
        """Reuse tokens and serialize renewal across polling, commands and SSE."""
        async with self._token_lock:
            if self._token and monotonic() < self._expires:
                return self._token
            self._check_cooldown()
            try:
                async with self.session.post(
                    TOKEN_URL,
                    data={
                        "client_id": self.client_id,
                        "client_secret": self._secret,
                        "grant_type": "client_credentials",
                    },
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=False,
                ) as response:
                    self._check_status(response, token=True)
                    data = await response.json()
                # The Swagger contract wraps tokens in {code, data}; the getting-started
                # guide also shows a plain OAuth response. Accept both formats.
                if isinstance(data, dict) and "code" in data:
                    if data["code"] not in (0, 200):
                        raise MammotionError("Mammotion reported an unsuccessful token response")
                    data = data.get("data")
                token = data.get("access_token") if isinstance(data, dict) else None
                if not isinstance(token, str) or not token:
                    raise MammotionError("Mammotion returned an unexpected token response")
                expires = float(data.get("expires_in", 3600))
                self._token = token
                self._expires = monotonic() + max(1, expires - min(60, expires / 10))
                return token
            except (aiohttp.ClientError, TimeoutError, ValueError, TypeError) as err:
                raise MammotionError("Could not obtain a valid Mammotion token") from err

    def invalidate_token(self, used_token: str) -> None:
        """Do not invalidate a newer token renewed by another request."""
        if self._token == used_token:
            self._expires = 0

    async def request(self, method: str, path: str, body: Any = None) -> Any:
        """Retry once only after HTTP 401; never retry ambiguous command failures."""
        for attempt in range(2):
            self._check_cooldown()
            token = await self.access_token()
            try:
                async with self.session.request(
                    method,
                    API_URL + path,
                    json=body,
                    headers={"Authorization": f"Bearer {token}", "Accept-Language": "en"},
                    timeout=aiohttp.ClientTimeout(total=30),
                    allow_redirects=False,
                ) as response:
                    if response.status == 401 and attempt == 0:
                        self.invalidate_token(token)
                        continue
                    self._check_status(response)
                    payload = await response.json()
                if not isinstance(payload, dict) or payload.get("code") not in (0, 200):
                    raise MammotionError("Mammotion reported an unsuccessful API response")
                data = payload.get("data")
                if isinstance(data, dict) and data.get("commandResult") is False:
                    raise MammotionError("Mammotion rejected the device command")
                return data
            except (aiohttp.ClientError, TimeoutError, ValueError) as err:
                raise MammotionError("Could not complete the Mammotion API request") from err
        raise AuthenticationError("Mammotion rejected the access token")

    async def mowers(self) -> list[dict[str, Any]]:
        data = await self.request("GET", "/v1/mowers")
        if not isinstance(data, list) or any(
            not isinstance(d, dict) or not d.get("id") for d in data
        ):
            raise MammotionError("Unexpected mower list from Mammotion")
        return data

    async def detail(self, device_id: str) -> dict[str, Any]:
        return object_data(await self.request("GET", f"/v1/mower/{quote(device_id, safe='')}"))

    async def plans(self, device_id: str) -> list[dict[str, Any]]:
        data = await self.request("GET", f"/v1/mower/{quote(device_id, safe='')}/plan")
        if not isinstance(data, list) or any(
            not isinstance(d, dict) or not d.get("taskName") for d in data
        ):
            raise MammotionError("Unexpected task list from Mammotion")
        return data

    async def work_params(self, device_id: str) -> dict[str, Any]:
        return object_data(
            await self.request("GET", f"/v1/mower/{quote(device_id, safe='')}/work-params")
        )

    async def action(self, device_id: str, action: str, task_name: str | None = None) -> Any:
        if action not in ACTIONS or (action == "START" and not task_name):
            raise MammotionError("START requires a task name; action must be documented")
        body: dict[str, Any] = {"deviceId": device_id, "action": action}
        if action == "START":
            body["params"] = {"taskName": task_name}
        return await self.request("POST", "/v1/mower/action", body)

    async def errors(self, device_id: str, **filters: Any) -> dict[str, Any]:
        return object_data(
            await self.request(
                "POST", "/v1/mower/error-codes/search", {"deviceId": device_id, **filters}
            )
        )

    async def subscribe(self, device_ids: list[str]) -> None:
        for offset in range(0, len(device_ids), 20):
            await self.request(
                "POST",
                "/v1/devices/subscriptions",
                [
                    {"deviceId": device_id, "properties": list(PROPERTIES)}
                    for device_id in device_ids[offset : offset + 20]
                ],
            )

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        self._check_cooldown()
        token = await self.access_token()
        try:
            async with self.session.get(
                API_URL + "/developer-sse/api/client/sse",
                headers={
                    "Authorization": f"Bearer {token}",
                    "SSE-Client": "developer",
                    "Accept": "text/event-stream",
                },
                timeout=aiohttp.ClientTimeout(total=None, sock_connect=30, sock_read=660),
                allow_redirects=False,
                read_bufsize=MAX_SSE_SIZE,
            ) as response:
                if response.status == 401:
                    self.invalidate_token(token)
                    raise MammotionError("SSE token expired; reconnect with a new token")
                self._check_status(response)
                if response.content_type != "text/event-stream":
                    raise MammotionError("Unexpected Mammotion SSE content type")
                async for message in sse_messages(response.content):
                    yield message
        except (aiohttp.ClientError, TimeoutError, UnicodeError) as err:
            raise MammotionError("Mammotion SSE connection interrupted") from err
