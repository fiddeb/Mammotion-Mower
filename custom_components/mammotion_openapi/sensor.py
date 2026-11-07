"""Documented mower and network sensor values."""

from dataclasses import dataclass

from homeassistant.components.sensor import (
    SensorDeviceClass,
    SensorEntity,
    SensorEntityDescription,
    SensorStateClass,
)
from homeassistant.const import PERCENTAGE, SIGNAL_STRENGTH_DECIBELS_MILLIWATT, EntityCategory

from .entity import MammotionEntity, discover

PARALLEL_UPDATES = 0


@dataclass(frozen=True, kw_only=True)
class MammotionSensorDescription(SensorEntityDescription):
    network: bool = False


SENSORS = (
    MammotionSensorDescription(
        key="batteryLevel",
        translation_key="battery",
        device_class=SensorDeviceClass.BATTERY,
        native_unit_of_measurement=PERCENTAGE,
        state_class=SensorStateClass.MEASUREMENT,
    ),
    MammotionSensorDescription(key="status", translation_key="status"),
    MammotionSensorDescription(
        key="version", translation_key="firmware", entity_category=EntityCategory.DIAGNOSTIC
    ),
    MammotionSensorDescription(
        key="usedNetwork",
        translation_key="network",
        network=True,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    MammotionSensorDescription(
        key="wifiIp",
        translation_key="wifi_ip",
        network=True,
        entity_category=EntityCategory.DIAGNOSTIC,
        entity_registry_enabled_default=False,
    ),
    MammotionSensorDescription(
        key="wifiRssi",
        translation_key="wifi_signal",
        network=True,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
        entity_category=EntityCategory.DIAGNOSTIC,
    ),
    MammotionSensorDescription(
        key="cellularRssi",
        translation_key="cellular_signal",
        network=True,
        device_class=SensorDeviceClass.SIGNAL_STRENGTH,
        native_unit_of_measurement=SIGNAL_STRENGTH_DECIBELS_MILLIWATT,
        state_class=SensorStateClass.MEASUREMENT,
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
                MammotionSensor(coordinator, device_id, description) for description in SENSORS
            ],
        )
    )


class MammotionSensor(MammotionEntity, SensorEntity):
    entity_description: MammotionSensorDescription

    def __init__(self, coordinator, device_id, description):
        super().__init__(coordinator, device_id, description.key)
        self.entity_description = description

    @property
    def native_value(self):
        if not self.mower:
            return None
        source = (
            self.mower.info.get("network") or {}
            if self.entity_description.network
            else self.mower.info
        )
        value = source.get(self.entity_description.key)
        if self.entity_description.key == "usedNetwork":
            return {"1": "Wi-Fi", "2": "Cellular"}.get(str(value))
        return value
