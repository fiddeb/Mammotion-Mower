"""Shared polling and optional LUBA 3 AWD SSE connection."""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import timedelta
from time import monotonic
from typing import Any

from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed, HomeAssistantError
from homeassistant.helpers.event import async_call_later
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .api import (
    AuthenticationError,
    MammotionClient,
    MammotionError,
    RateLimitError,
    StreamPreempted,
)
from .const import CONF_ENABLE_PUSH, CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL, DOMAIN

_LOGGER = logging.getLogger(__name__)


@dataclass
class MowerData:
    """Latest data and availability for one mower."""

    info: dict[str, Any]
    reachable: bool = False
    plans: list[dict[str, Any]] = field(default_factory=list)
    plans_available: bool = False
    plans_updated: float = 0
    work_params: dict[str, Any] = field(default_factory=dict)

    @property
    def online(self) -> bool:
        return self.info.get("online") in (1, True, "1")


class MammotionCoordinator(DataUpdateCoordinator[dict[str, MowerData]]):
    """One account, with independent availability for each mower."""

    def __init__(self, hass: HomeAssistant, entry: ConfigEntry, client: MammotionClient) -> None:
        super().__init__(
            hass,
            _LOGGER,
            name=DOMAIN,
            config_entry=entry,
            update_interval=timedelta(
                seconds=entry.options.get(CONF_POLL_INTERVAL, DEFAULT_POLL_INTERVAL)
            ),
        )
        self.client = client
        self.entry = entry
        self.selected_tasks: dict[str, str] = {}
        self.push_status = "disabled"
        self._push_refresh_cancel = None
        self._last_push_refresh = 0.0

    async def _async_update_data(self) -> dict[str, MowerData]:
        try:
            devices = await self.client.mowers()
            result: dict[str, MowerData] = {}
            for info in devices:
                device_id = str(info["id"])
                old = (self.data or {}).get(device_id)
                mower = MowerData(
                    info={**(old.info if old else {}), **info},
                    plans=old.plans if old else [],
                    plans_available=old.plans_available if old else False,
                    plans_updated=old.plans_updated if old else 0,
                    work_params=old.work_params if old else {},
                )
                result[device_id] = mower
                if not mower.online:
                    continue
                try:
                    mower.info.update(await self.client.detail(device_id))
                    mower.reachable = True
                except AuthenticationError, RateLimitError:
                    raise
                except MammotionError:
                    _LOGGER.debug("A Mammotion mower detail request failed")
                    continue
                if not mower.plans_updated or monotonic() - mower.plans_updated >= 900:
                    try:
                        mower.plans = await self.client.plans(device_id)
                        mower.plans_available = True
                        mower.plans_updated = monotonic()
                    except AuthenticationError, RateLimitError:
                        raise
                    except MammotionError:
                        mower.plans_available = False
            return result
        except AuthenticationError as err:
            raise ConfigEntryAuthFailed(str(err)) from err
        except MammotionError as err:
            raise UpdateFailed(str(err)) from err

    def start_push(self) -> None:
        """Use a config-entry-owned background task so unloading cancels the stream."""
        if not self.entry.options.get(CONF_ENABLE_PUSH, True):
            return
        self.push_status = "waiting"
        self.entry.async_create_background_task(self.hass, self._push_loop(), "Mammotion SSE")
        self.entry.async_on_unload(self._cancel_push_refresh)

    def _cancel_push_refresh(self) -> None:
        if self._push_refresh_cancel:
            self._push_refresh_cancel()
            self._push_refresh_cancel = None

    def _schedule_push_refresh(self) -> None:
        """Coalesce telemetry bursts; REST remains the authoritative typed state."""
        if self._push_refresh_cancel:
            return

        async def refresh(_now: Any) -> None:
            self._push_refresh_cancel = None
            self._last_push_refresh = monotonic()
            await self.async_request_refresh()

        delay = max(5, 15 - (monotonic() - self._last_push_refresh))
        self._push_refresh_cancel = async_call_later(self.hass, delay, refresh)

    async def _push_loop(self) -> None:
        backoff = 15
        while True:
            ids = [
                device_id
                for device_id, mower in (self.data or {}).items()
                if "LUBA 3 AWD" in str(mower.info.get("model", "")).upper()
            ]
            if not ids:
                self.push_status = "unsupported"
                await asyncio.sleep(60)
                continue
            try:
                self.push_status = "connecting"
                await self.client.subscribe(ids)
                # Renew before the documented ten-minute expiry. Always subscribe first.
                async with asyncio.timeout(540):
                    async for message in self.client.stream():
                        self.push_status = "connected"
                        backoff = 15
                        self.hass.bus.async_fire(
                            f"{DOMAIN}_message",
                            {
                                "config_entry_id": self.entry.entry_id,
                                "message": message,
                            },
                        )
                        self._schedule_push_refresh()
            except StreamPreempted:
                self.push_status = "preempted"
                _LOGGER.warning("Mammotion SSE taken over by another client; reload to reconnect")
                return
            except AuthenticationError:
                self.push_status = "permission_denied"
                _LOGGER.warning("Mammotion SSE permission denied; regular polling remains active")
                return
            except TimeoutError:
                continue  # Nine-minute renewal, not a transport failure.
            except MammotionError:
                self.push_status = "reconnecting"
                _LOGGER.debug("Mammotion SSE disconnected; retrying with backoff")
            await asyncio.sleep(backoff)
            backoff = min(300, backoff * 2)

    async def command(self, device_id: str, action: str, task_name: str | None = None) -> None:
        mower = (self.data or {}).get(device_id)
        if not self.last_update_success or not mower or not mower.online or not mower.reachable:
            raise HomeAssistantError("The Mammotion mower is unavailable")
        try:
            await self.client.action(device_id, action, task_name)
        except AuthenticationError as err:
            self.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except MammotionError as err:
            raise HomeAssistantError(str(err)) from err
        await self.async_request_refresh()
