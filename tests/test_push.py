"""SSE lifecycle: ordering, renewal, backoff, preemption and cancellation."""

import asyncio
from unittest.mock import AsyncMock, patch

import pytest

from custom_components.mammotion_openapi.api import (
    AuthenticationError,
    MammotionError,
    StreamPreempted,
)
from custom_components.mammotion_openapi.const import DOMAIN


@pytest.fixture
def coordinator(setup_integration):
    coordinator = setup_integration.runtime_data
    coordinator.data["mower-1"].info["model"] = "LUBA 3 AWD 5000"
    return coordinator


async def test_subscribe_before_stream_and_stop_when_preempted(hass, coordinator):
    order = []
    messages = []
    hass.bus.async_listen(f"{DOMAIN}_message", lambda event: messages.append(event.data))

    async def subscribe(ids):
        assert ids == ["mower-1"]
        order.append("subscribe")

    async def stream():
        order.append("stream")
        yield {"pushTag": "notify", "pushType": 5, "pushData": {"code": "1000"}}
        raise StreamPreempted("Taken over")

    with (
        patch.object(coordinator.client, "subscribe", side_effect=subscribe) as subscriptions,
        patch.object(coordinator.client, "stream", side_effect=stream),
    ):
        await coordinator._push_loop()
    await hass.async_block_till_done()
    coordinator._cancel_push_refresh()
    assert order == ["subscribe", "stream"]
    assert subscriptions.await_count == 1
    assert coordinator.push_status == "preempted"
    assert messages == [
        {
            "config_entry_id": coordinator.entry.entry_id,
            "message": {
                "pushTag": "notify",
                "pushType": 5,
                "pushData": {"code": "1000"},
            },
        }
    ]


async def test_renewal_resubscribes_without_error_backoff(coordinator):
    streams = 0

    async def stream():
        nonlocal streams
        streams += 1
        if streams == 1:
            raise TimeoutError("Simulated nine-minute renewal deadline")
        raise StreamPreempted("Stop after renewed subscription")
        yield  # pragma: no cover

    with (
        patch.object(coordinator.client, "subscribe") as subscriptions,
        patch.object(coordinator.client, "stream", side_effect=stream),
        patch("custom_components.mammotion_openapi.coordinator.asyncio.sleep") as sleep,
    ):
        await coordinator._push_loop()
    assert subscriptions.await_count == 2
    sleep.assert_not_called()


async def test_connection_errors_back_off(coordinator):
    with (
        patch.object(coordinator.client, "subscribe", side_effect=MammotionError("Offline")),
        patch(
            "custom_components.mammotion_openapi.coordinator.asyncio.sleep",
            new=AsyncMock(side_effect=[None, None, asyncio.CancelledError]),
        ) as sleep,
    ):
        with pytest.raises(asyncio.CancelledError):
            await coordinator._push_loop()
    assert [call.args[0] for call in sleep.await_args_list] == [15, 30, 60]


async def test_no_sse_for_unsupported_model(coordinator):
    coordinator.data["mower-1"].info["model"] = "LUBA 2 AWD"
    with (
        patch.object(coordinator.client, "subscribe") as subscribe,
        patch(
            "custom_components.mammotion_openapi.coordinator.asyncio.sleep",
            new=AsyncMock(side_effect=asyncio.CancelledError),
        ),
    ):
        with pytest.raises(asyncio.CancelledError):
            await coordinator._push_loop()
    subscribe.assert_not_called()
    assert coordinator.push_status == "unsupported"


async def test_permission_denial_keeps_polling_available(coordinator):
    with patch.object(coordinator.client, "subscribe", side_effect=AuthenticationError("Denied")):
        await coordinator._push_loop()
    assert coordinator.push_status == "permission_denied"
    assert coordinator.last_update_success


async def test_pending_push_refreshes_are_coalesced_and_cancelled(coordinator):
    coordinator._schedule_push_refresh()
    first = coordinator._push_refresh_cancel
    for _ in range(20):
        coordinator._schedule_push_refresh()
    assert coordinator._push_refresh_cancel is first
    coordinator._cancel_push_refresh()
    assert coordinator._push_refresh_cancel is None


async def test_unload_cancels_live_stream(hass, entry, api_mock):
    entered = asyncio.Event()
    closed = asyncio.Event()
    entry.add_to_hass(hass)
    hass.config_entries.async_update_entry(entry, options={"enable_push": True})

    async def stream():
        try:
            entered.set()
            await asyncio.Event().wait()
            yield  # pragma: no cover
        finally:
            closed.set()

    with (
        patch(
            "custom_components.mammotion_openapi.coordinator.MammotionClient.mowers",
            return_value=[{"id": "mower-1", "model": "LUBA 3 AWD", "online": 0}],
        ),
        patch("custom_components.mammotion_openapi.coordinator.MammotionClient.subscribe"),
        patch(
            "custom_components.mammotion_openapi.coordinator.MammotionClient.stream",
            side_effect=stream,
        ),
    ):
        assert await hass.config_entries.async_setup(entry.entry_id)
        await asyncio.wait_for(entered.wait(), timeout=5)
        assert await hass.config_entries.async_unload(entry.entry_id)
        await hass.async_block_till_done()
    assert closed.is_set()
