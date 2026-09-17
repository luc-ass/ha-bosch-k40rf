"""Config flow tests. Bronze requires this file to cover every branch."""

from __future__ import annotations

from ipaddress import ip_address
from unittest.mock import AsyncMock

from pyk40rf import K40AuthError, K40ConnectionError, K40Error, K40ProximityError, Token
import pytest
from pytest_homeassistant_custom_component.common import MockConfigEntry

from custom_components.bosch_k40rf.const import CONF_AUTH_PORT, DOMAIN
from homeassistant.config_entries import SOURCE_USER, SOURCE_ZEROCONF
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_PORT, CONF_TOKEN, CONF_USERNAME
from homeassistant.core import HomeAssistant
from homeassistant.data_entry_flow import FlowResultType
from homeassistant.helpers.service_info.zeroconf import ZeroconfServiceInfo

from .conftest import DEVICE_ID, HOST, PASSWORD, TOKEN

#: The TXT record the gateway actually publishes, measured with avahi-browse.
#: Note the hostname carries a different, shorter id than the instance name.
REAL_PROPERTIES = {
    "base_url": "/",
    "auth_version": "1.0.0",
    "serial": "10000000000000000000001",
    "uuid": DEVICE_ID,
    "brand": "Bosch",
    "model": "K40RF",
    "authport": "9442",
    "txtvers": "1",
}


def _zeroconf(
    host: str = HOST,
    name: str | None = None,
    port: int = 9443,
    properties: dict[str, str] | None = None,
) -> ZeroconfServiceInfo:
    """Build a discovery payload shaped like the gateway's real announcement."""
    return ZeroconfServiceInfo(
        ip_address=ip_address(host),
        ip_addresses=[ip_address(host)],
        hostname="K40RF-a1b2c3.local.",
        name=name or f"K40RF-{DEVICE_ID}._hvac-open-api._tcp.local.",
        port=port,
        type="_hvac-open-api._tcp.local.",
        properties=REAL_PROPERTIES if properties is None else properties,
    )


async def test_user_flow_pairs_the_gateway(hass: HomeAssistant, mock_client: AsyncMock) -> None:
    """The manual path: address, credentials, button press."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    assert result["type"] is FlowResultType.FORM
    assert result["step_id"] == "user"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    assert result["step_id"] == "credentials"

    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
    )
    assert result["step_id"] == "proximity"

    result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
    assert result["type"] is FlowResultType.CREATE_ENTRY
    assert result["data"] == {
        CONF_HOST: HOST,
        CONF_PORT: 9443,
        CONF_AUTH_PORT: 9442,
        CONF_USERNAME: DEVICE_ID,
        CONF_TOKEN: TOKEN,
    }
    assert result["result"].unique_id == DEVICE_ID


async def test_password_may_be_typed_without_dashes(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """The sticker prints dashes; the gateway does not want them."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: "aaaabbbbccccdddd"}
    )
    assert result["step_id"] == "proximity"


async def test_a_malformed_password_is_caught_before_the_gateway(
    hass: HomeAssistant, mock_client: AsyncMock
) -> None:
    """No point pressing buttons for a password that cannot be right."""
    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: "too-short"}
    )
    assert result["step_id"] == "credentials"
    assert result["errors"] == {CONF_PASSWORD: "invalid_password_format"}
    mock_client.async_request_token.assert_not_called()


class TestProximity:
    """The 412 the gateway gives when the buttons were not pressed."""

    async def test_proximity_failure_gets_its_own_message(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        mock_client.async_request_token.side_effect = K40ProximityError("nope")

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

        # Staying on the step matters: the user presses the buttons and retries.
        assert result["step_id"] == "proximity"
        assert result["errors"] == {"base": "proximity_required"}

    async def test_the_user_can_retry_after_pressing_the_buttons(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        mock_client.async_request_token.side_effect = [
            K40ProximityError("nope"),
            Token(access_token=TOKEN),
        ]

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

        assert result["type"] is FlowResultType.CREATE_ENTRY

    @pytest.mark.parametrize(
        ("error", "expected"),
        [
            (K40AuthError("bad"), "invalid_auth"),
            (K40ConnectionError("down"), "cannot_connect"),
            (K40Error("what"), "unknown"),
        ],
    )
    async def test_other_failures_map_to_their_own_messages(
        self, hass: HomeAssistant, mock_client: AsyncMock, error: Exception, expected: str
    ) -> None:
        mock_client.async_request_token.side_effect = error

        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

        assert result["errors"] == {"base": expected}

    async def test_a_token_from_elsewhere_can_be_pasted(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        """Home Assistant outside the gateway's subnet can never prove proximity."""
        result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_HOST: HOST}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_TOKEN: "pasted-token"}
        )

        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_TOKEN] == "pasted-token"
        mock_client.async_request_token.assert_not_called()


class TestZeroconf:
    """Discovery knows the host and the login already."""

    async def test_discovery_prefills_the_login(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf()
        )
        assert result["step_id"] == "discovery_confirm"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["step_id"] == "credentials"
        # The user only has to type the password.
        assert result["data_schema"]({CONF_PASSWORD: PASSWORD})[CONF_USERNAME] == DEVICE_ID

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["type"] is FlowResultType.CREATE_ENTRY
        assert result["data"][CONF_HOST] == HOST

    async def test_the_ports_come_from_the_announcement(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        """The service record carries both ports, so neither is hard-coded."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=_zeroconf(port=19443, properties={**REAL_PROPERTIES, "authport": "19442"}),
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

        assert result["data"][CONF_PORT] == 19443
        assert result["data"][CONF_AUTH_PORT] == 19442

        # Storing them is not enough: the token request itself has to use them.
        _, kwargs = mock_client.flow_factory.call_args
        assert kwargs["data_port"] == 19443
        assert kwargs["auth_port"] == 19442

    async def test_the_device_id_comes_from_the_txt_record(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        """The mDNS hostname carries a different id than the login."""
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=_zeroconf(name="unhelpful._hvac-open-api._tcp.local."),
        )
        assert result["step_id"] == "discovery_confirm"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        assert result["data_schema"]({CONF_PASSWORD: PASSWORD})[CONF_USERNAME] == DEVICE_ID

    @pytest.mark.parametrize("authport", ["", "nonsense", "0", "70000"])
    async def test_an_unusable_auth_port_falls_back(
        self, hass: HomeAssistant, mock_client: AsyncMock, authport: str
    ) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=_zeroconf(properties={**REAL_PROPERTIES, "authport": authport}),
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

        assert result["data"][CONF_AUTH_PORT] == 9442

    async def test_txt_values_may_arrive_as_bytes(
        self, hass: HomeAssistant, mock_client: AsyncMock
    ) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=_zeroconf(properties={"uuid": DEVICE_ID.encode(), "authport": b"9442"}),
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
        )
        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})

        assert result["result"].unique_id == DEVICE_ID
        assert result["data"][CONF_AUTH_PORT] == 9442

    async def test_a_foreign_service_is_rejected(self, hass: HomeAssistant) -> None:
        result = await hass.config_entries.flow.async_init(
            DOMAIN,
            context={"source": SOURCE_ZEROCONF},
            data=_zeroconf(name="Printer._hvac-open-api._tcp.local.", properties={}),
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "not_a_gateway"

    async def test_a_known_gateway_is_not_offered_twice(
        self, hass: HomeAssistant, config_entry: MockConfigEntry
    ) -> None:
        config_entry.add_to_hass(hass)
        result = await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf()
        )
        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "already_configured"

    async def test_a_moved_gateway_updates_its_address(
        self, hass: HomeAssistant, config_entry: MockConfigEntry
    ) -> None:
        """Gold rule discovery-update-info: a new lease must not break setup."""
        config_entry.add_to_hass(hass)
        await hass.config_entries.flow.async_init(
            DOMAIN, context={"source": SOURCE_ZEROCONF}, data=_zeroconf("192.0.2.77")
        )
        assert config_entry.data[CONF_HOST] == "192.0.2.77"


async def test_the_same_gateway_cannot_be_added_twice_manually(
    hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
) -> None:
    """The login is the device id, so it identifies the entry."""
    config_entry.add_to_hass(hass)

    result = await hass.config_entries.flow.async_init(DOMAIN, context={"source": SOURCE_USER})
    result = await hass.config_entries.flow.async_configure(result["flow_id"], {CONF_HOST: HOST})
    result = await hass.config_entries.flow.async_configure(
        result["flow_id"], {CONF_USERNAME: DEVICE_ID, CONF_PASSWORD: PASSWORD}
    )

    assert result["type"] is FlowResultType.ABORT
    assert result["reason"] == "already_configured"


class TestReauth:
    """What happens when a stored token stops being accepted."""

    async def test_reauth_replaces_the_token(
        self, hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
    ) -> None:
        config_entry.add_to_hass(hass)
        result = await config_entry.start_reauth_flow(hass)
        assert result["step_id"] == "reauth_confirm"

        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: PASSWORD}
        )
        assert result["step_id"] == "proximity"

        result = await hass.config_entries.flow.async_configure(result["flow_id"], {})
        # A successful reauth reloads the entry; let that finish before teardown.
        await hass.async_block_till_done()

        assert result["type"] is FlowResultType.ABORT
        assert result["reason"] == "reauth_successful"
        assert config_entry.data[CONF_TOKEN] == TOKEN

    async def test_reauth_validates_the_password_too(
        self, hass: HomeAssistant, mock_client: AsyncMock, config_entry: MockConfigEntry
    ) -> None:
        config_entry.add_to_hass(hass)
        result = await config_entry.start_reauth_flow(hass)
        result = await hass.config_entries.flow.async_configure(
            result["flow_id"], {CONF_PASSWORD: "nope"}
        )
        assert result["step_id"] == "reauth_confirm"
        assert result["errors"] == {CONF_PASSWORD: "invalid_password_format"}
