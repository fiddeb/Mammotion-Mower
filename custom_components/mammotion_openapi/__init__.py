"""Home Assistant integration using the official Mammotion Open API."""

from homeassistant.config_entries import ConfigEntry
from homeassistant.const import CONF_CLIENT_ID, CONF_CLIENT_SECRET
from homeassistant.core import HomeAssistant
from homeassistant.helpers.aiohttp_client import async_get_clientsession

from .api import MammotionClient
from .const import PLATFORMS
from .coordinator import MammotionCoordinator

type MammotionConfigEntry = ConfigEntry[MammotionCoordinator]


async def async_setup_entry(hass: HomeAssistant, entry: MammotionConfigEntry) -> bool:
    client = MammotionClient(
        async_get_clientsession(hass), entry.data[CONF_CLIENT_ID], entry.data[CONF_CLIENT_SECRET]
    )
    coordinator = MammotionCoordinator(hass, entry, client)
    await coordinator.async_config_entry_first_refresh()
    entry.runtime_data = coordinator
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)
    entry.async_on_unload(entry.add_update_listener(_async_options_updated))
    coordinator.start_push()
    return True


async def _async_options_updated(hass: HomeAssistant, entry: MammotionConfigEntry) -> None:
    await hass.config_entries.async_reload(entry.entry_id)


async def async_unload_entry(hass: HomeAssistant, entry: MammotionConfigEntry) -> bool:
    return await hass.config_entries.async_unload_platforms(entry, PLATFORMS)
