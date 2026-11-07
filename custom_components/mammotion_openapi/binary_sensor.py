"""Connectivity, charging and fault status."""

from homeassistant.components.binary_sensor import (
    BinarySensorDeviceClass,
    BinarySensorEntity,
    BinarySensorEntityDescription,
)
from homeassistant.const import EntityCategory

from .entity import MammotionEntity, discover

PARALLEL_UPDATES = 0
SENSORS = (
    BinarySensorEntityDescription(
        key="online",
        translation_key="online",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="chargeStatus",
        translation_key="charging",
        device_class=BinarySensorDeviceClass.BATTERY_CHARGING,
    ),
    BinarySensorEntityDescription(
        key="problem", translation_key="problem", device_class=BinarySensorDeviceClass.PROBLEM
    ),
    BinarySensorEntityDescription(
        key="wifiAvailable",
        translation_key="wifi_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    BinarySensorEntityDescription(
        key="cellularAvailable",
        translation_key="cellular_available",
        device_class=BinarySensorDeviceClass.CONNECTIVITY,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
)


async def async_setup_entry(hass, entry, async_add_entities):
    coordinator = entry.runtime_data
    entry.async_on_unload(
        discover(
            coordinator,
            async_add_entities,
            lambda device_id: [
                MammotionBinarySensor(coordinator, device_id, description)
                for description in SENSORS
            ],
        )
    )


class MammotionBinarySensor(MammotionEntity, BinarySensorEntity):
    def __init__(self, coordinator, device_id, description):
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def available(self):
        if self.entity_description.key == "online":
            return self.coordinator.last_update_success and self.mower is not None
        return super().available

    @property
    def is_on(self):
        if not self.mower:
            return None
        key = self.entity_description.key
        if key == "online":
            return self.mower.online
        if key == "problem":
            status = self.mower.info.get("status")
            return str(status).lower() == "abnormal" if status is not None else None
        source = (
            self.mower.info.get("network") or {} if key.endswith("Available") else self.mower.info
        )
        value = source.get(key)
        return value in (1, True, "1") if value is not None else None
