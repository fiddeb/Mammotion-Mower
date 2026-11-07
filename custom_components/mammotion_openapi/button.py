"""Extra actions not represented by the standard mower controls."""

from homeassistant.components.button import ButtonEntity, ButtonEntityDescription
from homeassistant.const import EntityCategory
from homeassistant.exceptions import HomeAssistantError

from .entity import MammotionEntity, discover

PARALLEL_UPDATES = 1
BUTTONS = (
    ButtonEntityDescription(key="start_task", translation_key="start_task"),
    ButtonEntityDescription(key="resume", translation_key="resume"),
    ButtonEntityDescription(key="cancel_return", translation_key="cancel_return"),
    ButtonEntityDescription(
        key="refresh", translation_key="refresh", entity_category=EntityCategory.DIAGNOSTIC
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entry.async_on_unload(
        discover(
            coordinator,
            async_add_entities,
            lambda device_id: [
                MammotionButton(coordinator, device_id, description) for description in BUTTONS
            ],
        )
    )


class MammotionButton(MammotionEntity, ButtonEntity):
    def __init__(self, coordinator, device_id, description):
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def available(self):
        if self.entity_description.key == "refresh":
            return self.mower is not None
        return super().available

    async def async_press(self):
        key = self.entity_description.key
        if key == "refresh":
            if self.mower:
                self.mower.plans_updated = 0
            await self.coordinator.async_request_refresh()
        elif key == "start_task":
            task_name = self.coordinator.selected_tasks.get(self.device_id)
            names = [task["taskName"] for task in self.mower.plans] if self.mower else []
            if not task_name or task_name not in names or not self.mower.plans_available:
                raise HomeAssistantError("Choose an available saved task before starting")
            await self.coordinator.command(self.device_id, "START", task_name)
        else:
            await self.coordinator.command(
                self.device_id, "RESUME" if key == "resume" else "CANCEL_RETURN"
            )
