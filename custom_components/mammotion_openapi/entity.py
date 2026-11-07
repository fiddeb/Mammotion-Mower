"""Common device identity, availability and discovery."""

from collections.abc import Callable

from homeassistant.core import callback
from homeassistant.helpers.device_registry import DeviceInfo
from homeassistant.helpers.entity import Entity
from homeassistant.helpers.update_coordinator import CoordinatorEntity

from .const import DOMAIN
from .coordinator import MammotionCoordinator


class MammotionEntity(CoordinatorEntity[MammotionCoordinator]):
    _attr_has_entity_name = True

    def __init__(self, coordinator: MammotionCoordinator, device_id: str, key: str) -> None:
        super().__init__(coordinator)
        self.device_id = device_id
        self._attr_unique_id = f"{device_id}_{key}"

    @property
    def mower(self):
        return self.coordinator.data.get(self.device_id)

    @property
    def available(self) -> bool:
        return bool(super().available and self.mower and self.mower.online and self.mower.reachable)

    @property
    def device_info(self) -> DeviceInfo:
        info = self.mower.info if self.mower else {}
        return DeviceInfo(
            identifiers={(DOMAIN, self.device_id)},
            manufacturer="Mammotion",
            name=info.get("nickname") or info.get("name") or "Mammotion mower",
            model=info.get("model"),
            sw_version=info.get("version"),
        )


@callback
def discover(
    coordinator: MammotionCoordinator, async_add_entities, factory: Callable[[str], list[Entity]]
) -> Callable[[], None]:
    """Add entities when new mowers appear, without requiring a reload."""
    known: set[str] = set()

    @callback
    def update() -> None:
        new_ids = coordinator.data.keys() - known
        for device_id in new_ids:
            async_add_entities(factory(device_id))
        known.update(new_ids)

    update()
    return coordinator.async_add_listener(update)
