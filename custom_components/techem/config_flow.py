"""Config flow for the Techem integration."""

from __future__ import annotations

import logging
import re
from typing import Any

import homeassistant.helpers.config_validation as cv
import voluptuous as vol
from homeassistant.config_entries import (
    ConfigEntry,
    ConfigFlow,
    ConfigFlowResult,
    OptionsFlow,
)
from homeassistant.const import (
    CONF_EMAIL,
    CONF_HOST,
    CONF_PASSWORD,
    CONF_SCAN_INTERVAL,
)
from homeassistant.core import callback
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.selector import (
    SelectSelector,
    SelectSelectorConfig,
    SelectSelectorMode,
)

from .api import TechemAuthError, TechemClient, TechemError
from .const import (
    CONF_OBJECT_ID,
    DEFAULT_API_HOST,
    DEFAULT_SCAN_INTERVAL_HOURS,
    DOMAIN,
    KNOWN_HOSTS,
    MAX_SCAN_INTERVAL_HOURS,
    MIN_SCAN_INTERVAL_HOURS,
)
from .discovery import unit_label

_LOGGER = logging.getLogger(__name__)

HOST_PATTERN = re.compile(r"^[a-z0-9][a-z0-9.-]*[a-z0-9]$")

STEP_USER_SCHEMA = vol.Schema(
    {
        vol.Required(CONF_EMAIL): cv.string,
        vol.Required(CONF_PASSWORD): cv.string,
        vol.Required(CONF_HOST, default=DEFAULT_API_HOST): SelectSelector(
            SelectSelectorConfig(
                options=sorted(KNOWN_HOSTS),
                mode=SelectSelectorMode.DROPDOWN,
                custom_value=True,
            )
        ),
    }
)


def normalise_host(value: str) -> str | None:
    """Reduce user input to a bare hostname, or None if it is not one.

    Accepts what people are likely to paste -- a full portal URL, a trailing
    slash, mixed case -- and rejects anything that is not a plain hostname so
    the API URL cannot be pointed somewhere unintended.
    """
    host = value.strip().lower()
    host = re.sub(r"^[a-z]+://", "", host)
    host = host.split("/", 1)[0].split("?", 1)[0]
    # A tenant portal URL still identifies the right API host.
    host = re.sub(r"^(beboer|kunde|mieter|www)\.", "", host)
    if not host or not HOST_PATTERN.match(host) or ".." in host:
        return None
    return host


class TechemConfigFlow(ConfigFlow, domain=DOMAIN):
    """Handle a config flow for Techem."""

    VERSION = 1

    def __init__(self) -> None:
        """Initialise the flow."""
        self._client: TechemClient | None = None
        self._credentials: dict[str, str] = {}
        self._units: list[dict[str, Any]] = []

    @staticmethod
    @callback
    def async_get_options_flow(config_entry: ConfigEntry) -> OptionsFlow:
        """Return the options flow."""
        return TechemOptionsFlow()

    async def async_step_user(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect credentials and look up the available units."""
        errors: dict[str, str] = {}

        if user_input is not None:
            host = normalise_host(user_input[CONF_HOST])
            if host is None:
                errors[CONF_HOST] = "invalid_host"
            else:
                user_input = {**user_input, CONF_HOST: host}

        if user_input is not None and not errors:
            session = async_get_clientsession(self.hass)
            client = TechemClient(
                session,
                user_input[CONF_HOST],
                user_input[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )

            try:
                await client.async_verify_credentials()
                units = await client.async_get_units()
            except TechemAuthError:
                errors["base"] = "invalid_auth"
            except TechemError as err:
                _LOGGER.debug("Techem setup failed: %s", err)
                errors["base"] = "cannot_connect"
            else:
                if not units:
                    errors["base"] = "no_units"
                else:
                    self._client = client
                    self._credentials = dict(user_input)
                    self._units = units
                    if len(units) == 1:
                        return await self._async_create_entry(units[0])
                    return await self.async_step_unit()

        return self.async_show_form(
            step_id="user", data_schema=STEP_USER_SCHEMA, errors=errors
        )

    async def async_step_unit(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Pick a unit when the account has more than one."""
        if user_input is not None:
            chosen = next(
                (
                    u
                    for u in self._units
                    if str(u.get("id")) == user_input[CONF_OBJECT_ID]
                ),
                None,
            )
            if chosen is not None:
                return await self._async_create_entry(chosen)

        options = {str(u.get("id")): unit_label(u) for u in self._units}
        return self.async_show_form(
            step_id="unit",
            data_schema=vol.Schema({vol.Required(CONF_OBJECT_ID): vol.In(options)}),
        )

    async def _async_create_entry(self, unit: dict[str, Any]) -> ConfigFlowResult:
        """Finish setup for the chosen unit."""
        assert self._client is not None

        object_id = str(unit.get("id"))
        # Qualify with the host so the same unit id on two country servers
        # cannot collide.
        await self.async_set_unique_id(f"{self._credentials[CONF_HOST]}:{object_id}")
        self._abort_if_unique_id_configured()

        return self.async_create_entry(
            title=unit_label(unit),
            data={**self._credentials, CONF_OBJECT_ID: object_id},
        )

    async def async_step_reauth(self, entry_data: dict[str, Any]) -> ConfigFlowResult:
        """Start reauthentication after the stored password stopped working."""
        return await self.async_step_reauth_confirm()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for a fresh password."""
        errors: dict[str, str] = {}
        entry = self._get_reauth_entry()

        if user_input is not None:
            session = async_get_clientsession(self.hass)
            client = TechemClient(
                session,
                entry.data.get(CONF_HOST, DEFAULT_API_HOST),
                entry.data[CONF_EMAIL],
                user_input[CONF_PASSWORD],
            )
            try:
                await client.async_verify_credentials()
            except TechemAuthError:
                errors["base"] = "invalid_auth"
            except TechemError:
                errors["base"] = "cannot_connect"
            else:
                return self.async_update_reload_and_abort(
                    entry, data_updates={CONF_PASSWORD: user_input[CONF_PASSWORD]}
                )

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): cv.string}),
            description_placeholders={"email": entry.data[CONF_EMAIL]},
            errors=errors,
        )


class TechemOptionsFlow(OptionsFlow):
    """Handle Techem options."""

    async def async_step_init(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user adjust how often Techem is polled."""
        if user_input is not None:
            return self.async_create_entry(data=user_input)

        current = self.config_entry.options.get(
            CONF_SCAN_INTERVAL, DEFAULT_SCAN_INTERVAL_HOURS
        )
        return self.async_show_form(
            step_id="init",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_SCAN_INTERVAL, default=current): vol.All(
                        vol.Coerce(int),
                        vol.Range(
                            min=MIN_SCAN_INTERVAL_HOURS, max=MAX_SCAN_INTERVAL_HOURS
                        ),
                    )
                }
            ),
        )
