"""Config flow for the Bosch K 40 RF integration."""

from __future__ import annotations

from collections.abc import Mapping
import logging
from typing import Any

from pyk40rf import (
    AUTH_PORT,
    DATA_PORT,
    TXT_AUTH_PORT,
    TXT_DEVICE_ID,
    K40AuthError,
    K40Client,
    K40ConnectionError,
    K40Error,
    K40ProximityError,
    SystemInfo,
    device_id_from_zeroconf_name,
    is_valid_password,
)
import voluptuous as vol

from homeassistant.config_entries import ConfigFlow, ConfigFlowResult
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_TOKEN, CONF_USERNAME
from homeassistant.helpers.aiohttp_client import async_get_clientsession
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .const import CONF_AUTH_PORT, DOMAIN

_LOGGER = logging.getLogger(__name__)

STEP_USER_SCHEMA = vol.Schema({vol.Required(CONF_HOST): str})


class K40ConfigFlow(ConfigFlow, domain=DOMAIN):
    """Walk the user through pairing one gateway.

    There are two ways in, and the user picks between them up front. Pairing
    fetches a token from the gateway, which needs the sticker password, a
    button press on the device *and* a request from its own subnet. Pasting a
    token skips all three: it is the only credential the integration stores,
    so a user who runs Home Assistant elsewhere, rotates tokens themselves, or
    simply will not type the sticker password never has to.
    """

    VERSION = 1

    def __init__(self) -> None:
        """Start with nothing known."""
        self._host: str | None = None
        self._device_id: str | None = None
        self._username: str | None = None
        self._password: str | None = None
        self._port: int = DATA_PORT
        self._auth_port: int = AUTH_PORT

    async def async_step_user(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Take the gateway's address from the user.

        Nothing is verified here: the gateway is only contacted in the
        proximity step, and failing there gives the user a message they can
        act on rather than a bare "cannot connect".
        """
        if user_input is not None:
            self._host = user_input[CONF_HOST].strip()
            return await self.async_step_auth_method()

        return self.async_show_form(step_id="user", data_schema=STEP_USER_SCHEMA)

    async def async_step_zeroconf(self, discovery_info: ZeroconfServiceInfo) -> ConfigFlowResult:
        """Handle a gateway that announced itself on the network.

        The service record carries everything the user would otherwise type:
        the data port, the token endpoint in its ``authport`` property, and the
        device id in ``uuid`` -- which is also the login. Only the password on
        the sticker is left to enter.

        The id is read from the TXT record rather than the mDNS hostname: the
        hostname uses a different, shorter id (``K40RF-a1b2c3.local``) than the
        instance name, and the login follows the instance name.
        """
        properties = {
            str(key).lower(): value for key, value in (discovery_info.properties or {}).items()
        }
        device_id = _text(properties.get(TXT_DEVICE_ID)) or device_id_from_zeroconf_name(
            discovery_info.name
        )
        if device_id is None:
            return self.async_abort(reason="not_a_gateway")

        await self.async_set_unique_id(device_id)
        self._abort_if_unique_id_configured(
            updates={CONF_HOST: discovery_info.host, CONF_PORT: discovery_info.port or DATA_PORT}
        )

        self._host = discovery_info.host
        self._device_id = device_id
        self._username = device_id
        self._port = discovery_info.port or DATA_PORT
        self._auth_port = _port(properties.get(TXT_AUTH_PORT), AUTH_PORT)
        self.context["title_placeholders"] = {"name": f"K 40 RF {device_id}"}
        return await self.async_step_discovery_confirm()

    async def async_step_discovery_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Let the user confirm the discovered gateway before pairing it."""
        if user_input is not None:
            return await self.async_step_auth_method()

        return self.async_show_form(
            step_id="discovery_confirm",
            description_placeholders={"host": self._host or "", "device_id": self._device_id or ""},
        )

    async def async_step_auth_method(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask how the gateway should be authenticated.

        Both branches end in the same entry; they differ only in who obtains
        the token. Reauth offers the same choice, so a token the user manages
        themselves can be replaced by another one.
        """
        pair_step = "reauth_confirm" if self.source == "reauth" else "credentials"
        return self.async_show_menu(
            step_id="auth_method",
            menu_options=[pair_step, "token"],
            description_placeholders={"host": self._host or ""},
        )

    async def async_step_credentials(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Collect the login and password from the device sticker."""
        errors: dict[str, str] = {}

        if user_input is not None:
            username = user_input[CONF_USERNAME].strip()
            password = user_input[CONF_PASSWORD].strip()

            if not is_valid_password(password):
                errors[CONF_PASSWORD] = "invalid_password_format"
            else:
                self._username = username
                self._password = password
                if not self.unique_id:
                    await self.async_set_unique_id(username)
                    self._abort_if_unique_id_configured()
                return await self.async_step_proximity()

        schema = vol.Schema(
            {
                vol.Required(CONF_USERNAME, default=self._username or ""): str,
                vol.Required(CONF_PASSWORD): str,
            }
        )
        return self.async_show_form(step_id="credentials", data_schema=schema, errors=errors)

    async def async_step_proximity(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Fetch the token, which requires the buttons to have just been pressed.

        Fetching the token is also the connection test, so a success here means
        the entry is known to work.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            try:
                token = await self._async_fetch_token()
            except K40ProximityError:
                errors["base"] = "proximity_required"
            except K40AuthError:
                errors["base"] = "invalid_auth"
            except K40ConnectionError:
                errors["base"] = "cannot_connect"
            except K40Error:
                _LOGGER.exception("Unexpected error while pairing the gateway")
                errors["base"] = "unknown"
            else:
                return self._create_entry(token)

        return self.async_show_form(
            step_id="proximity",
            data_schema=vol.Schema({}),
            errors=errors,
            description_placeholders={"host": self._host or ""},
        )

    async def async_step_token(self, user_input: dict[str, Any] | None = None) -> ConfigFlowResult:
        """Take a token the user obtained elsewhere.

        Reading ``/system/basicInfo`` does double duty: it proves the token is
        accepted -- nothing else in this branch talks to the gateway -- and it
        names the gateway the token belongs to, which is the entry's unique id.
        """
        errors: dict[str, str] = {}

        if user_input is not None:
            token = user_input[CONF_TOKEN].strip()

            try:
                system_info = await self._async_read_system_info(token)
            except K40AuthError:
                errors["base"] = "invalid_token"
            except K40ConnectionError:
                errors["base"] = "cannot_connect"
            except K40Error:
                _LOGGER.exception("Unexpected error while checking a token")
                errors["base"] = "unknown"
            else:
                # The gateway's own id outranks a discovered one: it names the
                # device this token actually opens, which is what reauth has
                # to compare against.
                device_id = system_info.gateway_id or self._username
                if device_id is None:
                    errors["base"] = "no_gateway_id"
                else:
                    self._username = device_id
                    await self.async_set_unique_id(device_id)
                    if self.source == "reauth":
                        self._abort_if_unique_id_mismatch()
                    else:
                        self._abort_if_unique_id_configured()
                    return self._create_entry(token)

        return self.async_show_form(
            step_id="token",
            data_schema=vol.Schema({vol.Required(CONF_TOKEN): str}),
            errors=errors,
            description_placeholders={"host": self._host or ""},
        )

    async def async_step_reauth(self, entry_data: Mapping[str, Any]) -> ConfigFlowResult:
        """Start over when the stored token stops being accepted."""
        self._host = entry_data.get(CONF_HOST)
        self._username = entry_data.get(CONF_USERNAME)
        self._port = entry_data.get(CONF_PORT, DATA_PORT)
        self._auth_port = entry_data.get(CONF_AUTH_PORT, AUTH_PORT)
        return await self.async_step_auth_method()

    async def async_step_reauth_confirm(
        self, user_input: dict[str, Any] | None = None
    ) -> ConfigFlowResult:
        """Ask for the password again and fetch a fresh token."""
        errors: dict[str, str] = {}

        if user_input is not None:
            password = user_input[CONF_PASSWORD].strip()
            if not is_valid_password(password):
                errors[CONF_PASSWORD] = "invalid_password_format"
            else:
                self._password = password
                return await self.async_step_proximity()

        return self.async_show_form(
            step_id="reauth_confirm",
            data_schema=vol.Schema({vol.Required(CONF_PASSWORD): str}),
            errors=errors,
            description_placeholders={"host": self._host or ""},
        )

    async def _async_fetch_token(self) -> str:
        """Ask the gateway for a bearer token."""
        client = K40Client(
            str(self._host),
            async_get_clientsession(self.hass, verify_ssl=False),
            data_port=self._port,
            auth_port=self._auth_port,
        )
        token = await client.async_request_token(
            str(self._username), str(self._password), store=False
        )
        return token.access_token

    async def _async_read_system_info(self, token: str) -> SystemInfo:
        """Read the gateway's own description with a token, to check both."""
        client = K40Client(
            str(self._host),
            async_get_clientsession(self.hass, verify_ssl=False),
            token=token,
            data_port=self._port,
            auth_port=self._auth_port,
        )
        return await client.async_get_system_info()

    def _create_entry(self, token: str) -> ConfigFlowResult:
        """Store the paired gateway, or update an existing entry on reauth."""
        data = {
            CONF_HOST: self._host,
            CONF_PORT: self._port,
            CONF_AUTH_PORT: self._auth_port,
            CONF_USERNAME: self._username,
            CONF_TOKEN: token,
        }

        if self.source == "reauth":
            return self.async_update_reload_and_abort(
                self._get_reauth_entry(), data_updates={CONF_TOKEN: token}
            )

        return self.async_create_entry(title=f"K 40 RF {self._username}", data=data)


def _text(value: object) -> str | None:
    """Read an mDNS TXT value, which may arrive as bytes."""
    if isinstance(value, bytes):
        value = value.decode("utf-8", "replace")
    text = str(value).strip() if value is not None else ""
    return text or None


def _port(value: object, default: int) -> int:
    """Read a port from an mDNS TXT value, falling back to the default."""
    text = _text(value)
    if text is None:
        return default
    try:
        port = int(text)
    except ValueError:
        return default
    return port if 0 < port < 65536 else default
