"""Data coordinators for the Bosch K 40 RF integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from pyk40rf import Installation, K40AuthError, K40Client, K40Error, Resource

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed

from .const import DOMAIN, SCAN_INTERVAL, SIGNAL_SCAN_INTERVAL
from .resources import ResourceCandidate, candidates_for
from .types import K40ConfigEntry

_LOGGER = logging.getLogger(__name__)


class K40BaseCoordinator(DataUpdateCoordinator[dict[str, Resource]]):
    """Shared polling behaviour for both coordinators."""

    config_entry: K40ConfigEntry

    def __init__(
        self,
        hass: HomeAssistant,
        entry: K40ConfigEntry,
        client: K40Client,
        name: str,
        update_interval: timedelta,
    ) -> None:
        """Initialise the coordinator."""
        super().__init__(
            hass,
            _LOGGER,
            config_entry=entry,
            name=name,
            update_interval=update_interval,
        )
        self.client = client
        self._paths: list[str] = []

    @property
    def paths(self) -> list[str]:
        """The resources this coordinator polls."""
        return list(self._paths)

    async def _fetch(self, paths: list[str]) -> dict[str, Resource]:
        """Read ``paths``, translating library errors into coordinator ones."""
        if not paths:
            return {}
        try:
            return await self.client.async_get_many(paths)
        except K40AuthError as err:
            # The token is not accepted any more; only the user can fix that.
            _LOGGER.error("Gateway rejected the token while polling: %s", err)
            raise ConfigEntryAuthFailed(
                translation_domain=DOMAIN, translation_key="auth_failed"
            ) from err
        except K40Error as err:
            raise UpdateFailed(
                translation_domain=DOMAIN,
                translation_key="cannot_connect",
                translation_placeholders={"error": str(err)},
            ) from err


class K40DataCoordinator(K40BaseCoordinator):
    """Polls the live readings.

    The gateway serves one resource per request, so a poll is dozens of round
    trips. The set of resources is settled once at setup -- whatever answered
    is what gets polled -- rather than re-probed every minute.
    """

    def __init__(self, hass: HomeAssistant, entry: K40ConfigEntry, client: K40Client) -> None:
        """Initialise the live-reading coordinator."""
        super().__init__(hass, entry, client, f"{DOMAIN} data", SCAN_INTERVAL)
        self.candidates: list[ResourceCandidate] = []

    async def async_resolve(self, installation: Installation) -> dict[str, Resource]:
        """Find out which declared resources this gateway actually answers.

        The first read doubles as the probe: resources that 404 are dropped by
        the client, so what comes back is exactly what exists here.
        """
        self.candidates = candidates_for(installation)
        resources = await self._fetch([candidate.path for candidate in self.candidates])

        present = set(resources)
        self.candidates = [c for c in self.candidates if c.path in present]
        self._paths = [c.path for c in self.candidates]

        _LOGGER.debug(
            "%s of %s declared resources are present on this gateway",
            len(self._paths),
            len(candidates_for(installation)),
        )
        return resources

    async def _async_update_data(self) -> dict[str, Resource]:
        """Poll every resource known to be present."""
        return await self._fetch(self._paths)


class K40SignalCoordinator(K40BaseCoordinator):
    """Polls the diagnostic ``/signals`` branch.

    These entities are disabled by default and the values move slowly, so they
    are polled on a much slower schedule than the live readings, and not at all
    while every one of them is disabled.
    """

    def __init__(self, hass: HomeAssistant, entry: K40ConfigEntry, client: K40Client) -> None:
        """Initialise the signal coordinator."""
        super().__init__(hass, entry, client, f"{DOMAIN} signals", SIGNAL_SCAN_INTERVAL)

    def set_signals(self, signals: tuple[str, ...]) -> None:
        """Record which signal resources this gateway offers."""
        self._paths = list(signals)

    async def _async_update_data(self) -> dict[str, Resource]:
        """Poll the signals that have at least one enabled entity."""
        if not self.async_contexts_available:
            return self.data or {}
        return await self._fetch(self._paths)

    @property
    def async_contexts_available(self) -> bool:
        """Whether any entity is actually listening."""
        return bool(list(self.async_contexts()))
