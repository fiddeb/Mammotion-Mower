"""Contract, authentication and failure semantics of the real async HTTP client."""

import asyncio
from datetime import UTC, datetime, timedelta
from email.utils import format_datetime
from unittest.mock import patch

import pytest
from aiohttp import StreamReader
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from pytest_homeassistant_custom_component.test_util.aiohttp import AiohttpClientMockResponse

from custom_components.mammotion_openapi.api import (
    MAX_SSE_SIZE,
    AuthenticationError,
    MammotionClient,
    MammotionError,
    RateLimitError,
    StreamPreempted,
    object_data,
    sse_messages,
)
from custom_components.mammotion_openapi.const import ACTIONS, API_URL, TOKEN_URL


@pytest.fixture
async def client(hass, aioclient_mock):
    return MammotionClient(async_get_clientsession(hass), "test-client", "test-secret")


async def test_token_cached_for_concurrent_reads(client, api_mock):
    results = await asyncio.gather(*(client.mowers() for _ in range(5)))
    assert len(results) == 5
    token_calls = [call for call in api_mock.mock_calls if str(call[1]) == TOKEN_URL]
    assert len(token_calls) == 1
    assert token_calls[0][2] == {
        "client_id": "test-client",
        "client_secret": "test-secret",
        "grant_type": "client_credentials",
    }
    assert api_mock.mock_calls[-1][3]["Authorization"] == "Bearer test-token"


async def test_expired_token_is_renewed(client, api_mock):
    await client.mowers()
    client._expires = 0
    await client.mowers()
    assert sum(str(call[1]) == TOKEN_URL for call in api_mock.mock_calls) == 2


@pytest.mark.parametrize("code", [0, 200])
async def test_token_in_response_envelope_is_accepted_and_expiry_used(client, aioclient_mock, code):
    aioclient_mock.post(
        TOKEN_URL,
        json={
            "code": code,
            "msg": "Success",
            "data": {
                "access_token": "wrapped-token",
                "expires_in": 120,
                "token_type": "Bearer",
            },
        },
    )
    aioclient_mock.get(API_URL + "/v1/mowers", json={"code": 0, "data": []})
    with patch("custom_components.mammotion_openapi.api.monotonic", return_value=100):
        assert await client.mowers() == []
        assert client._expires == 208
        assert await client.access_token() == "wrapped-token"
    assert aioclient_mock.call_count == 2
    assert aioclient_mock.mock_calls[-1][3]["Authorization"] == "Bearer wrapped-token"


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 500, "data": {"access_token": "must-not-be-used"}},
        {"code": 0, "data": None},
        {"code": 0, "data": []},
        {"code": 0, "data": {"refresh_token": "private-refresh-token"}},
        {"expires_in": 3600},
    ],
)
async def test_unexpected_token_response_is_not_misreported_as_bad_credentials(
    client, aioclient_mock, payload
):
    aioclient_mock.post(TOKEN_URL, json=payload)
    with pytest.raises(MammotionError) as raised:
        await client.mowers()
    assert not isinstance(raised.value, AuthenticationError)
    assert "private-refresh-token" not in str(raised.value)
    assert aioclient_mock.call_count == 1


async def test_401_refreshes_once(client, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "new-token", "expires_in": 3600})
    attempts = 0

    async def respond(method, url, data):
        nonlocal attempts
        attempts += 1
        return AiohttpClientMockResponse(
            method, url, status=401 if attempts == 1 else 200, json={"code": 200, "data": []}
        )

    aioclient_mock.get(API_URL + "/v1/mowers", side_effect=respond)
    assert await client.mowers() == []
    assert attempts == 2
    assert sum(str(call[1]) == TOKEN_URL for call in aioclient_mock.mock_calls) == 2


async def test_permanent_401_stops_after_one_retry(client, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "new-token"})
    aioclient_mock.get(API_URL + "/v1/mowers", status=401)
    with pytest.raises(AuthenticationError):
        await client.mowers()
    assert aioclient_mock.call_count == 4


@pytest.mark.parametrize("status", [400, 401, 403])
async def test_bad_credentials(client, aioclient_mock, status):
    aioclient_mock.post(TOKEN_URL, status=status)
    with pytest.raises(AuthenticationError):
        await client.mowers()


@pytest.mark.parametrize(
    "retry_after",
    ["120", "invalid", format_datetime(datetime.now(UTC) + timedelta(minutes=2), usegmt=True)],
)
async def test_rate_limit_blocks_following_commands(client, aioclient_mock, retry_after):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token"})
    aioclient_mock.get(API_URL + "/v1/mowers", status=429, headers={"Retry-After": retry_after})
    with pytest.raises(RateLimitError):
        await client.mowers()
    calls = aioclient_mock.call_count
    with pytest.raises(RateLimitError):
        await client.action("mower-1", "CMD_START")
    assert aioclient_mock.call_count == calls


@pytest.mark.parametrize("action", ACTIONS)
async def test_all_documented_commands(client, api_mock, action):
    await client.action("mower-1", action, "Framsidan" if action == "START" else None)
    body = api_mock.mock_calls[-1][2]
    assert body == {
        "deviceId": "mower-1",
        "action": action,
        **({"params": {"taskName": "Framsidan"}} if action == "START" else {}),
    }


@pytest.mark.parametrize("action,task", [("START", None), ("START", ""), ("REBOOT", None)])
async def test_invalid_commands_do_not_reach_network(client, aioclient_mock, action, task):
    with pytest.raises(MammotionError):
        await client.action("mower-1", action, task)
    assert aioclient_mock.call_count == 0


async def test_command_timeout_never_retries(client, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token"})
    aioclient_mock.post(API_URL + "/v1/mower/action", exc=TimeoutError())
    with pytest.raises(MammotionError):
        await client.action("mower-1", "CMD_START")
    assert aioclient_mock.call_count == 2


@pytest.mark.parametrize(
    "payload",
    [
        {"code": 500, "msg": "test-secret"},
        {"code": 200, "data": {"commandResult": False, "resultMessage": "test-secret"}},
        ["bad"],
    ],
)
async def test_unsuccessful_response_is_safe(client, aioclient_mock, payload):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token"})
    aioclient_mock.post(API_URL + "/v1/mower/action", json=payload)
    with pytest.raises(MammotionError) as raised:
        await client.action("mower-1", "CMD_START")
    assert "test-secret" not in str(raised.value)


@pytest.mark.parametrize("data", [None, {}, [{"name": "Missing ID"}]])
async def test_malformed_list_is_rejected(client, aioclient_mock, data):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token"})
    aioclient_mock.get(API_URL + "/v1/mowers", json={"code": 200, "data": data})
    with pytest.raises(MammotionError):
        await client.mowers()


def test_singleton_detail_from_getting_started_guide():
    assert object_data([{"id": "mower-1"}]) == {"id": "mower-1"}
    with pytest.raises(MammotionError):
        object_data([])


async def test_subscription_batches_at_twenty(client, api_mock):
    api_mock.post(
        API_URL + "/v1/devices/subscriptions",
        json={
            "code": 200,
            "data": {
                "commandResult": True,
            },
        },
    )
    await client.subscribe([str(index) for index in range(43)])
    bodies = [call[2] for call in api_mock.mock_calls if str(call[1]).endswith("/subscriptions")]
    assert [len(body) for body in bodies] == [20, 20, 3]
    assert "ERR_CODE" in bodies[0][0]["properties"]
    assert "MSG_NOTICE" in bodies[0][0]["properties"]


class Lines:
    def __init__(self, text):
        self.lines = iter(text.encode().splitlines(keepends=True))

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.lines)
        except StopIteration:
            raise StopAsyncIteration from None


async def test_sse_comments_heartbeats_multiline_and_notification():
    lines = Lines(
        ": heartbeat\r\ndata: :: Connect to server successful ::\r\n\r\n"
        'data: {"pushTag":"notify",\n'
        'data: "pushType":5,"pushData":{"deviceId":"mower-1","code":"1000"}}\n\n'
    )
    assert [message async for message in sse_messages(lines)] == [
        {
            "pushTag": "notify",
            "pushType": 5,
            "pushData": {"deviceId": "mower-1", "code": "1000"},
        }
    ]


@pytest.mark.parametrize("push_type", ['"1"', "1"])
async def test_sse_preemption_stops_consumer(push_type):
    with pytest.raises(StreamPreempted):
        async for _ in sse_messages(Lines(f'data: {{"pushTag":"sc","pushType":{push_type}}}\n\n')):
            pytest.fail("Preemption must not be delivered as device data")


async def test_sse_headers_and_preemption(client, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token"})
    aioclient_mock.get(
        API_URL + "/developer-sse/api/client/sse",
        headers={
            "Content-Type": "text/event-stream",
        },
        text='data: {"pushTag":"sc","pushType":"1"}\n\n',
    )
    # Real stream framing is tested above; this isolates request headers and close behavior.
    with patch("custom_components.mammotion_openapi.api.sse_messages") as messages:

        async def kicked(_content):
            raise StreamPreempted("Taken over")
            yield  # pragma: no cover

        messages.side_effect = kicked
        with pytest.raises(StreamPreempted):
            async for _ in client.stream():
                pass
    assert aioclient_mock.mock_calls[-1][3] == {
        "Authorization": "Bearer token",
        "SSE-Client": "developer",
        "Accept": "text/event-stream",
    }


@pytest.mark.parametrize(
    "buffer_limit,payload_size,accepted",
    [
        (MAX_SSE_SIZE, 140_000, True),
        (65_536, 140_000, False),
        (MAX_SSE_SIZE, 1_100_000, False),
    ],
)
async def test_real_stream_reader_enforces_safe_size_limits(buffer_limit, payload_size, accepted):
    from unittest.mock import Mock

    protocol = Mock(_reading_paused=False)
    reader = StreamReader(protocol, limit=buffer_limit)
    reader.feed_data(b'data: {"private_track":"' + b"x" * payload_size + b'"}\n\n')
    reader.feed_eof()
    if accepted:
        messages = [message async for message in sse_messages(reader)]
        assert len(messages[0]["private_track"]) == payload_size
    else:
        with pytest.raises(MammotionError) as raised:
            async for _ in sse_messages(reader):
                pytest.fail("Oversized message must be rejected")
        assert "private_track" not in str(raised.value)
        assert raised.value.__suppress_context__ or raised.value.__context__ is None


async def test_detail_params_and_error_search_contract(client, api_mock):
    api_mock.get(
        API_URL + "/v1/mower/mower-1/work-params",
        json={
            "code": 200,
            "data": {"knifeHeight": 50, "speed": 0.3},
        },
    )
    page = {"records": [{"code": 1000, "solution": "Inspect"}], "hasMore": True, "total": 12}
    api_mock.post(API_URL + "/v1/mower/error-codes/search", json={"code": 200, "data": page})
    assert (await client.detail("mower-1"))["batteryLevel"] == 78
    assert await client.work_params("mower-1") == {"knifeHeight": 50, "speed": 0.3}
    assert await client.errors("mower-1", pageNumber=2, pageSize=10, errorCode="1000") == page
    assert api_mock.mock_calls[-1][2] == {
        "deviceId": "mower-1",
        "pageNumber": 2,
        "pageSize": 10,
        "errorCode": "1000",
    }
