"""Tests for the Techem config flow."""

from __future__ import annotations

from unittest.mock import patch

import pytest
from homeassistant import config_entries
from homeassistant.const import CONF_EMAIL, CONF_HOST, CONF_PASSWORD, CONF_SCAN_INTERVAL
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType, InvalidData
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.techem.config_flow import normalise_host
from custom_components.techem.const import CONF_OBJECT_ID, DOMAIN

from .conftest import FakeSession, TechemApiMock
from .const import MOCK_EMAIL, MOCK_HOST, MOCK_OBJECT_ID, MOCK_PASSWORD, MOCK_UNIQUE_ID

USER_INPUT = {
    CONF_EMAIL: MOCK_EMAIL,
    CONF_PASSWORD: MOCK_PASSWORD,
    CONF_HOST: MOCK_HOST,
}


@pytest.fixture
def patched_session(session: FakeSession):
    """Give the config flow our fake aiohttp session."""
    with patch(
        "custom_components.techem.config_flow.async_get_clientsession",
        return_value=session,
    ):
        yield session


# -- host normalisation ---------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("techemadmin.no", "techemadmin.no"),
        ("techemadmin.dk", "techemadmin.dk"),
        ("TechemAdmin.NO", "techemadmin.no"),
        ("  techemadmin.dk  ", "techemadmin.dk"),
        # People paste the portal URL, which still identifies the API host.
        ("https://beboer.techemadmin.no/", "techemadmin.no"),
        ("beboer.techemadmin.no", "techemadmin.no"),
        ("https://techemadmin.no/analytics/graphql", "techemadmin.no"),
    ],
)
def test_normalise_host_accepts(raw: str, expected: str) -> None:
    """Realistic input is reduced to a bare hostname."""
    assert normalise_host(raw) == expected


@pytest.mark.parametrize(
    "raw",
    ["", "   ", "a..b", "-bad.com", "host_underscore.no", "techemadmin.no:8080",
     "javascript:alert(1)"],
)
def test_normalise_host_rejects(raw: str) -> None:
    """Anything that is not a plain hostname is refused."""
    assert normalise_host(raw) is None


# -- the flow itself ------------------------------------------------------


async def test_single_unit_creates_entry(
    hass: HomeAssistant, patched_session: FakeSession
) -> None:
    """One unit on the account means no picker step."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OBJECT_ID] == MOCK_OBJECT_ID
    assert result["data"][CONF_HOST] == MOCK_HOST
    assert result["result"].unique_id == MOCK_UNIQUE_ID


async def test_multiple_units_shows_picker(
    hass: HomeAssistant, patched_session: FakeSession, api: TechemApiMock
) -> None:
    """More than one unit means the user chooses which to set up."""
    first = api.units[0]
    second = dict(first)
    second["id"] = "objecttest0000000002"
    second["unit"] = {**(first.get("unit") or {}), "unitNumber": "H0202"}
    api.units = [first, second]

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "unit"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_OBJECT_ID: "objecttest0000000002"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_OBJECT_ID] == "objecttest0000000002"


async def test_invalid_auth_shown_and_recoverable(
    hass: HomeAssistant, patched_session: FakeSession, api: TechemApiMock
) -> None:
    """A rejected password re-shows the form, then succeeds when corrected."""
    api.login_error = "invalid-credentials"

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}

    api.login_error = None
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    await hass.async_block_till_done()
    assert result["type"] is FlowResultType.CREATE_ENTRY


async def test_cannot_connect(
    hass: HomeAssistant, patched_session: FakeSession, api: TechemApiMock
) -> None:
    """A server error is reported as a connection problem."""
    api.status = 500

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "cannot_connect"}


async def test_no_units(
    hass: HomeAssistant, patched_session: FakeSession, api: TechemApiMock
) -> None:
    """An account with no metered units cannot be set up."""
    api.units = []

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )
    assert result["errors"] == {"base": "no_units"}


async def test_invalid_host_is_rejected_before_any_request(
    hass: HomeAssistant, patched_session: FakeSession, api: TechemApiMock
) -> None:
    """A bad hostname fails validation without contacting anything."""
    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {**USER_INPUT, CONF_HOST: "not a host"}
    )

    assert result["errors"] == {CONF_HOST: "invalid_host"}
    assert api.calls == []


async def test_duplicate_unit_aborts(
    hass: HomeAssistant, patched_session: FakeSession, mock_config_entry
) -> None:
    """Setting up the same unit twice aborts rather than duplicating."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(
        DOMAIN, context={"source": config_entries.SOURCE_USER}
    )
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], USER_INPUT
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


# -- reauth ---------------------------------------------------------------


async def test_reauth_updates_password(
    hass: HomeAssistant, patched_session: FakeSession, mock_config_entry
) -> None:
    """Re-authentication stores the new password on the existing entry."""
    mock_config_entry.add_to_hass(hass)

    result = await mock_config_entry.start_reauth_flow(hass)
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "reauth_confirm"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "new-password"}
    )
    await hass.async_block_till_done()

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "reauth_successful"
    assert mock_config_entry.data[CONF_PASSWORD] == "new-password"


async def test_reauth_rejects_wrong_password(
    hass: HomeAssistant,
    patched_session: FakeSession,
    api: TechemApiMock,
    mock_config_entry,
) -> None:
    """A still-wrong password keeps the form open."""
    mock_config_entry.add_to_hass(hass)
    api.login_error = "invalid-credentials"

    result = await mock_config_entry.start_reauth_flow(hass)
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_PASSWORD: "still-wrong"}
    )

    assert result["type"] is FlowResultType.FORM
    assert result["errors"] == {"base": "invalid_auth"}
    assert mock_config_entry.data[CONF_PASSWORD] == MOCK_PASSWORD


# -- options --------------------------------------------------------------


async def test_options_flow_sets_interval(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """The poll interval is adjustable."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    assert result["type"] is FlowResultType.FORM

    result = await hass.config_entries.options.async_configure(
        result["flow_id"], {CONF_SCAN_INTERVAL: 12}
    )
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"][CONF_SCAN_INTERVAL] == 12


async def test_options_flow_rejects_out_of_range(
    hass: HomeAssistant, mock_config_entry: MockConfigEntry
) -> None:
    """Absurd intervals are refused by the schema."""
    mock_config_entry.add_to_hass(hass)

    result = await hass.config_entries.options.async_init(
        mock_config_entry.entry_id
    )
    with pytest.raises(InvalidData):
        await hass.config_entries.options.async_configure(
            result["flow_id"], {CONF_SCAN_INTERVAL: 999}
        )
