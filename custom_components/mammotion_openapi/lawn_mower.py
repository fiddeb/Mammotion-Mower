"""Mower controls and automation actions."""

import voluptuous as vol
from homeassistant.components.lawn_mower import (
    LawnMowerActivity,
    LawnMowerEntity,
    LawnMowerEntityFeature,
)
from homeassistant.core import SupportsResponse
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers import config_validation as cv
from homeassistant.helpers import entity_platform

from .api import AuthenticationError, MammotionError
from .const import ACTIONS
from .entity import MammotionEntity, discover

PARALLEL_UPDATES = 1
ACTIVITIES = {
    "standby": LawnMowerActivity.IDLE,
    "working": LawnMowerActivity.MOWING,
    "paused": LawnMowerActivity.PAUSED,
    "returning": LawnMowerActivity.RETURNING,
    "abnormal": LawnMowerActivity.ERROR,
}


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entry.async_on_unload(
        discover(
            coordinator,
            async_add_entities,
            lambda device_id: [MammotionLawnMower(coordinator, device_id)],
        )
    )
    platform = entity_platform.async_get_current_platform()
    platform.async_register_entity_service(
        "start_task",
        {
            vol.Required("task_name"): cv.string,
        },
        "async_start_task",
    )
    platform.async_register_entity_service(
        "send_command",
        {
            vol.Required("command"): vol.In(ACTIONS),
            vol.Optional("task_name"): cv.string,
        },
        "async_send_command",
    )
    platform.async_register_entity_service(
        "get_error_history",
        {
            vol.Optional("page_number", default=1): vol.All(vol.Coerce(int), vol.Range(min=1)),
            vol.Optional("page_size", default=10): vol.All(
                vol.Coerce(int), vol.Range(min=1, max=100)
            ),
            vol.Optional("start_date"): cv.date,
            vol.Optional("end_date"): cv.date,
            vol.Optional("error_code"): cv.string,
        },
        "async_get_error_history",
        supports_response=SupportsResponse.ONLY,
    )
    platform.async_register_entity_service(
        "get_work_parameters",
        {},
        "async_get_work_parameters",
        supports_response=SupportsResponse.ONLY,
    )


class MammotionLawnMower(MammotionEntity, LawnMowerEntity):
    _attr_name = None
    _attr_supported_features = (
        LawnMowerEntityFeature.START_MOWING
        | LawnMowerEntityFeature.PAUSE
        | LawnMowerEntityFeature.STOP
        | LawnMowerEntityFeature.DOCK
    )

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id, "mower")

    @property
    def activity(self):
        if not self.mower:
            return None
        if self.mower.info.get("chargeStatus") in (1, True, "1"):
            return LawnMowerActivity.DOCKED
        return ACTIVITIES.get(str(self.mower.info.get("status", "")).lower())

    async def async_start_mowing(self):
        command = "RESUME" if self.activity == LawnMowerActivity.PAUSED else "CMD_START"
        await self.coordinator.command(self.device_id, command)

    async def async_pause(self):
        await self.coordinator.command(self.device_id, "PAUSE")

    async def async_stop(self):
        await self.coordinator.command(self.device_id, "STOP")

    async def async_dock(self):
        await self.coordinator.command(self.device_id, "RETURN")

    async def async_start_task(self, task_name):
        await self.coordinator.command(self.device_id, "START", task_name)

    async def async_send_command(self, command, task_name=None):
        await self.coordinator.command(self.device_id, command, task_name)

    async def _read(self, operation):
        try:
            return await operation
        except AuthenticationError as err:
            self.coordinator.entry.async_start_reauth(self.hass)
            raise HomeAssistantError(str(err)) from err
        except MammotionError as err:
            raise HomeAssistantError(str(err)) from err

    async def async_get_error_history(
        self, page_number=1, page_size=10, start_date=None, end_date=None, error_code=None
    ):
        if start_date and end_date and start_date > end_date:
            raise HomeAssistantError("Start date must be before or equal to end date")
        filters = {"pageNumber": page_number, "pageSize": page_size}
        if start_date:
            filters["startDate"] = start_date.isoformat()
        if end_date:
            filters["endDate"] = end_date.isoformat()
        if error_code is not None:
            filters["errorCode"] = error_code
        return await self._read(self.coordinator.client.errors(self.device_id, **filters))

    async def async_get_work_parameters(self):
        result = await self._read(self.coordinator.client.work_params(self.device_id))
        if self.mower:
            self.mower.work_params = result
            self.coordinator.async_update_listeners()
        return result
