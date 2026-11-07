"""End-to-end entity, service and lifecycle tests in Home Assistant."""

from unittest.mock import patch

import pytest
from homeassistant.const import STATE_UNAVAILABLE, STATE_UNKNOWN
from homeassistant.core import State
from homeassistant.exceptions import HomeAssistantError
from pytest_homeassistant_custom_component.common import mock_restore_cache

from custom_components.mammotion_openapi.api import AuthenticationError, MammotionError
from custom_components.mammotion_openapi.const import DOMAIN
from custom_components.mammotion_openapi.diagnostics import async_get_config_entry_diagnostics

from .conftest import DETAIL, INFO, PLANS


async def test_entities_and_values(hass, setup_integration):
    assert hass.states.get("lawn_mower.roboten").state == "idle"
    assert hass.states.get("sensor.roboten_battery").state == "78"
    assert hass.states.get("sensor.roboten_network").state == "Wi-Fi"
    assert hass.states.get("sensor.roboten_wi_fi_signal").state == "-46"
    assert hass.states.get("binary_sensor.roboten_online").state == "on"
    assert hass.states.get("binary_sensor.roboten_charging").state == "off"
    assert hass.states.get("binary_sensor.roboten_problem").state == "off"
    assert hass.states.get("sensor.roboten_wi_fi_ip_address") is None
    assert hass.states.get("select.roboten_saved_task").attributes["options"] == ["Framsidan"]


@pytest.mark.parametrize(
    "service,command",
    [
        ("start_mowing", "CMD_START"),
        ("pause", "PAUSE"),
        ("stop", "STOP"),
        ("dock", "RETURN"),
    ],
)
async def test_standard_controls(hass, setup_integration, api_mock, service, command):
    await hass.services.async_call(
        "lawn_mower", service, {"entity_id": "lawn_mower.roboten"}, blocking=True
    )
    calls = [call for call in api_mock.mock_calls if str(call[1]).endswith("/action")]
    assert calls[-1][2] == {"deviceId": "mower-1", "action": command}


@pytest.mark.parametrize(
    "status,charge,expected",
    [
        ("Working", 0, "mowing"),
        ("Paused", 0, "paused"),
        ("Returning", 0, "returning"),
        ("Standby", 1, "docked"),
        ("Abnormal", 0, "error"),
        ("Mapping", 0, STATE_UNKNOWN),
        ("Updating", 0, STATE_UNKNOWN),
        ("FutureStatus", 0, STATE_UNKNOWN),
    ],
)
async def test_activity_mapping(hass, setup_integration, status, charge, expected):
    coordinator = setup_integration.runtime_data
    coordinator.data["mower-1"].info.update(status=status, chargeStatus=charge)
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.roboten").state == expected
    assert hass.states.get("sensor.roboten_status").state == status


async def test_start_when_paused_resumes(hass, setup_integration, api_mock):
    coordinator = setup_integration.runtime_data
    coordinator.data["mower-1"].info["status"] = "Paused"
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    await hass.services.async_call(
        "lawn_mower",
        "start_mowing",
        {
            "entity_id": "lawn_mower.roboten",
        },
        blocking=True,
    )
    assert any(
        call[2] == {"deviceId": "mower-1", "action": "RESUME"} for call in api_mock.mock_calls
    )


async def test_selecting_task_does_not_mow_and_button_starts(hass, setup_integration, api_mock):
    before = api_mock.call_count
    await hass.services.async_call(
        "select",
        "select_option",
        {
            "entity_id": "select.roboten_saved_task",
            "option": "Framsidan",
        },
        blocking=True,
    )
    assert api_mock.call_count == before
    await hass.services.async_call(
        "button",
        "press",
        {
            "entity_id": "button.roboten_start_selected_task",
        },
        blocking=True,
    )
    assert any(
        call[2]
        == {
            "deviceId": "mower-1",
            "action": "START",
            "params": {
                "taskName": "Framsidan",
            },
        }
        for call in api_mock.mock_calls
    )


async def test_task_button_requires_selection(hass, setup_integration, api_mock):
    before = api_mock.call_count
    with pytest.raises(HomeAssistantError):
        await hass.services.async_call(
            "button",
            "press",
            {
                "entity_id": "button.roboten_start_selected_task",
            },
            blocking=True,
        )
    assert api_mock.call_count == before


async def test_start_task_service(hass, setup_integration, api_mock):
    await hass.services.async_call(
        DOMAIN,
        "start_task",
        {
            "entity_id": "lawn_mower.roboten",
            "task_name": "Framsidan",
        },
        blocking=True,
    )
    assert any(
        call[2]
        == {
            "deviceId": "mower-1",
            "action": "START",
            "params": {
                "taskName": "Framsidan",
            },
        }
        for call in api_mock.mock_calls
    )


async def test_response_services(hass, setup_integration):
    coordinator = setup_integration.runtime_data
    page = {"records": [{"code": 1000, "solution": "Check mower"}], "total": 1, "hasMore": False}
    with patch.object(coordinator.client, "errors", return_value=page) as errors:
        response = await hass.services.async_call(
            DOMAIN,
            "get_error_history",
            {
                "entity_id": "lawn_mower.roboten",
                "start_date": "2026-11-01",
                "end_date": "2026-11-07",
                "error_code": "1000",
                "page_number": 2,
            },
            blocking=True,
            return_response=True,
        )
    errors.assert_awaited_once_with(
        "mower-1",
        pageNumber=2,
        pageSize=10,
        startDate="2026-11-01",
        endDate="2026-11-07",
        errorCode="1000",
    )
    assert response == {"lawn_mower.roboten": page}
    params = {"knifeHeight": 50, "speed": 0.3}
    with patch.object(coordinator.client, "work_params", return_value=params):
        response = await hass.services.async_call(
            DOMAIN,
            "get_work_parameters",
            {
                "entity_id": "lawn_mower.roboten",
            },
            blocking=True,
            return_response=True,
        )
    assert response == {"lawn_mower.roboten": params}


async def test_offline_connectivity_stays_visible_and_commands_blocked(hass, setup_integration):
    coordinator = setup_integration.runtime_data
    coordinator.data["mower-1"].info["online"] = 0
    coordinator.async_update_listeners()
    await hass.async_block_till_done()
    assert hass.states.get("binary_sensor.roboten_online").state == "off"
    assert hass.states.get("sensor.roboten_battery").state == STATE_UNAVAILABLE
    assert hass.states.get("lawn_mower.roboten").state == STATE_UNAVAILABLE
    with patch.object(coordinator.client, "action") as action:
        with pytest.raises(HomeAssistantError):
            await coordinator.command("mower-1", "CMD_START")
    action.assert_not_called()


async def test_one_detail_failure_does_not_hide_healthy_mower(hass, setup_integration):
    coordinator = setup_integration.runtime_data
    with (
        patch.object(
            coordinator.client,
            "mowers",
            return_value=[
                INFO,
                {
                    **INFO,
                    "id": "mower-2",
                    "nickname": "Second mower",
                },
            ],
        ),
        patch.object(
            coordinator.client,
            "detail",
            side_effect=[
                MammotionError("Unavailable"),
                {**DETAIL, "id": "mower-2", "nickname": "Second mower"},
            ],
        ),
        patch.object(coordinator.client, "plans", return_value=PLANS),
    ):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.roboten").state == STATE_UNAVAILABLE
    assert hass.states.get("lawn_mower.second_mower").state == "idle"


async def test_removed_device_becomes_unavailable(hass, setup_integration):
    coordinator = setup_integration.runtime_data
    with patch.object(coordinator.client, "mowers", return_value=[]):
        await coordinator.async_refresh()
        await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.roboten").state == STATE_UNAVAILABLE


async def test_command_auth_failure_starts_reauth(hass, setup_integration):
    coordinator = setup_integration.runtime_data
    with (
        patch.object(coordinator.client, "action", side_effect=AuthenticationError("Rejected")),
        patch.object(setup_integration, "async_start_reauth") as reauth,
    ):
        with pytest.raises(HomeAssistantError):
            await coordinator.command("mower-1", "CMD_START")
    reauth.assert_called_once_with(hass)


async def test_diagnostics_omit_identifying_fields(hass, setup_integration):
    import json

    diagnostic = json.dumps(await async_get_config_entry_diagnostics(hass, setup_integration))
    for secret in ("test-secret", "test-client", "test-token", "mower-1", "Roboten", "192.0.2.1"):
        assert secret not in diagnostic
    assert "LUBA 2 AWD 5000" in diagnostic


async def test_unload_removes_entities(hass, setup_integration):
    assert await hass.config_entries.async_unload(setup_integration.entry_id)
    await hass.async_block_till_done()
    assert hass.states.get("lawn_mower.roboten").state == STATE_UNAVAILABLE


async def test_plans_and_refresh_work_immediately_after_host_boot(hass, entry, api_mock):
    entry.add_to_hass(hass)
    with patch("custom_components.mammotion_openapi.coordinator.monotonic", return_value=100):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
        assert hass.states.get("select.roboten_saved_task").attributes["options"] == ["Framsidan"]
        await hass.services.async_call(
            "button",
            "press",
            {
                "entity_id": "button.roboten_refresh",
            },
            blocking=True,
        )
    assert sum(str(call[1]).endswith("/plan") for call in api_mock.mock_calls) == 2


async def test_selection_restored_while_offline_survives_recovery(hass, entry, api_mock):
    mock_restore_cache(hass, [State("select.roboten_saved_task", "Framsidan")])
    entry.add_to_hass(hass)
    with patch(
        "custom_components.mammotion_openapi.api.MammotionClient.mowers",
        return_value=[{**INFO, "online": 0}],
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await hass.async_block_till_done()
    coordinator = entry.runtime_data
    assert coordinator.selected_tasks["mower-1"] == "Framsidan"
    await coordinator.async_refresh()
    await hass.async_block_till_done()
    assert hass.states.get("select.roboten_saved_task").state == "Framsidan"
