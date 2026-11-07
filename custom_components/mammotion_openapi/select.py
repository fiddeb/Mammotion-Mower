"""A saved task selection; selecting never starts the mower."""

from homeassistant.components.select import SelectEntity
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.exceptions import HomeAssistantError
from homeassistant.helpers.restore_state import RestoreEntity

from .entity import MammotionEntity, discover

PARALLEL_UPDATES = 0


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entry.async_on_unload(
        discover(
            coordinator,
            async_add_entities,
            lambda device_id: [MammotionTaskSelect(coordinator, device_id)],
        )
    )


class MammotionTaskSelect(MammotionEntity, SelectEntity, RestoreEntity):
    _attr_translation_key = "task"

    def __init__(self, coordinator, device_id):
        super().__init__(coordinator, device_id, "task")

    async def async_added_to_hass(self):
        await super().async_added_to_hass()
        if (last := await self.async_get_last_state()) and last.state not in (
            STATE_UNKNOWN,
            STATE_UNAVAILABLE,
        ):
            self.coordinator.selected_tasks[self.device_id] = last.state

    @property
    def available(self):
        return bool(super().available and self.mower.plans_available and self.options)

    @property
    def options(self):
        return (
            list(dict.fromkeys(task["taskName"] for task in self.mower.plans)) if self.mower else []
        )

    @property
    def current_option(self):
        selected = self.coordinator.selected_tasks.get(self.device_id)
        return selected if selected in self.options else None

    async def async_select_option(self, option):
        if option not in self.options:
            raise HomeAssistantError("The selected Mammotion task is no longer available")
        self.coordinator.selected_tasks[self.device_id] = option
        self.async_write_ha_state()
