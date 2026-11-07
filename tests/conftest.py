"""Fixtures for an actual Home Assistant instance with mocked external HTTP."""

import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.mammotion_openapi.const import API_URL, DOMAIN, TOKEN_URL

INFO = {
    "id": "mower-1",
    "name": "Luba",
    "nickname": "Roboten",
    "model": "LUBA 2 AWD 5000",
    "online": 1,
}
DETAIL = {
    **INFO,
    "version": "1.2.3.4",
    "status": "StandBy",
    "batteryLevel": 78,
    "chargeStatus": 0,
    "network": {
        "usedNetwork": "1",
        "wifiAvailable": True,
        "wifiRssi": -46,
        "wifiIp": "192.0.2.1",
        "cellularAvailable": False,
        "cellularRssi": -90,
    },
}
PLANS = [{"taskId": "plan-1", "taskName": "Framsidan"}]


@pytest.fixture(autouse=True)
def custom_integrations(enable_custom_integrations):
    """Permit the custom component under test."""


@pytest.fixture
def api_mock(aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "test-token", "expires_in": 3600})
    aioclient_mock.get(API_URL + "/v1/mowers", json={"code": 200, "data": [INFO]})
    aioclient_mock.get(API_URL + "/v1/mower/mower-1", json={"code": 200, "data": DETAIL})
    aioclient_mock.get(API_URL + "/v1/mower/mower-1/plan", json={"code": 200, "data": PLANS})
    aioclient_mock.post(
        API_URL + "/v1/mower/action",
        json={
            "code": 200,
            "data": {"commandResult": True},
        },
    )
    return aioclient_mock


@pytest.fixture
def entry():
    return MockConfigEntry(
        domain=DOMAIN,
        title="Mammotion Open API",
        unique_id="test-client",
        data={"client_id": "test-client", "client_secret": "test-secret"},
        options={"enable_push": False},
    )


@pytest.fixture
async def setup_integration(hass, entry, api_mock):
    entry.add_to_hass(hass)
    assert await hass.config_entries.async_setup(entry.entry_id)
    await hass.async_block_till_done()
    return entry
