"""UI setup and credential lifecycle."""

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.data_entry_flow import FlowResultType

from custom_components.mammotion_openapi.const import API_URL, DOMAIN, TOKEN_URL

CREDS = {"client_id": "test-client", "client_secret": "test-secret"}


async def test_user_form_and_setup(hass, api_mock):
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": "user"})
    assert result["type"] == FlowResultType.FORM
    with patch("custom_components.mammotion_openapi.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_configure(result["flow_id"], CREDS)
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert result["data"] == CREDS
    assert result["result"].unique_id == "test-client"


@pytest.mark.parametrize("status,error", [(401, "invalid_auth"), (500, "cannot_connect")])
async def test_invalid_credentials_or_connection(hass, aioclient_mock, status, error):
    aioclient_mock.post(TOKEN_URL, status=status)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=CREDS
    )
    assert result["type"] == FlowResultType.FORM
    assert result["errors"] == {"base": error}


async def test_duplicate_entry(hass, entry, api_mock):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": "user"}, data=CREDS
    )
    assert result["type"] == FlowResultType.ABORT
    assert result["reason"] == "already_configured"


async def test_empty_account_can_be_configured(hass, aioclient_mock):
    aioclient_mock.post(TOKEN_URL, json={"access_token": "token"})
    aioclient_mock.get(API_URL + "/v1/mowers", json={"code": 200, "data": []})
    with patch("custom_components.mammotion_openapi.async_setup_entry", return_value=True):
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": "user"}, data=CREDS
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY


@pytest.mark.parametrize(
    "source,step,reason",
    [
        (config_entries.SOURCE_REAUTH, "reauth_confirm", "reauth_successful"),
        (config_entries.SOURCE_RECONFIGURE, "reconfigure", "reconfigure_successful"),
    ],
)
async def test_credential_renewal(hass, entry, api_mock, source, step, reason):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={"source": source, "entry_id": entry.entry_id},
        data=entry.data if source == config_entries.SOURCE_REAUTH else None,
    )
    assert result["step_id"] == step
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"],
            {
                **CREDS,
                "client_secret": "rotated-secret",
            },
        )
        await hass.async_block_till_done()
    assert result["reason"] == reason
    assert entry.data["client_secret"] == "rotated-secret"


async def test_reauth_cannot_switch_accounts(hass, entry, api_mock):
    entry.add_to_hass(hass)
    result = await hass.config_entries.flow.async_init(
        DOMAIN,
        context={
            "source": config_entries.SOURCE_REAUTH,
            "entry_id": entry.entry_id,
        },
        data=entry.data,
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"],
        {
            **CREDS,
            "client_id": "other-account",
        },
    )
    assert result["reason"] == "unique_id_mismatch"
    assert entry.data == CREDS


async def test_options(hass, setup_integration):
    entry = setup_integration
    result = await hass.config_entries.options.async_init(entry.entry_id)
    assert result["type"] == FlowResultType.FORM
    with patch.object(hass.config_entries, "async_reload", return_value=True):
        result = await hass.config_entries.options.async_configure(
            result["flow_id"],
            {
                "poll_interval": 120,
                "enable_push": False,
            },
        )
        await hass.async_block_till_done()
    assert result["type"] == FlowResultType.CREATE_ENTRY
    assert entry.options == {"poll_interval": 120, "enable_push": False}
