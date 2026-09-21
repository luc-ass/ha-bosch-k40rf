"""Data coordinators for the Bosch K 40 RF integration."""

from __future__ import annotations

from datetime import timedelta
import logging

from pyk40rf import Installation, K40AuthError, K40Client, K40Error, Resource

from homeassistant.core import HomeAssistant
from homeassistant.exceptions import ConfigEntryAuthFailed
from homeassistant.helpers.update_coordinator import DataUpdateCoordinator, UpdateFailed
from homeassistant.util import dt as dt_util

from .const import DOMAIN, INSTALLATION_PROBE_INTERVAL, SCAN_INTERVAL, SIGNAL_SCAN_INTERVAL
from .devices import build_device_tree
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
        self.installation = Installation()
        self._probed_at = dt_util.utcnow()

    async def async_resolve(self, installation: Installation) -> dict[str, Resource]:
        """Find out which declared resources this gateway actually answers.

        The first read doubles as the probe: resources that 404 are dropped by
        the client, so what comes back is exactly what exists here.
        """
        self.installation = installation
        self.candidates = candidates_for(installation)
        resources = await self._fetch([candidate.path for candidate in self.candidates])

        present = set(resources)
        self.candidates = [c for c in self.candidates if c.path in present]
        self._paths = [c.path for c in self.candidates]
        self._probed_at = dt_util.utcnow()

        _LOGGER.debug(
            "%s of %s declared resources are present on this gateway",
            len(self._paths),
            len(candidates_for(installation)),
        )
        return resources

    async def _async_update_data(self) -> dict[str, Resource]:
        """Poll every resource known to be present, probing now and then."""
        if dt_util.utcnow() - self._probed_at >= INSTALLATION_PROBE_INTERVAL:
            await self._async_probe_installation()
        return await self._fetch(self._paths)

    async def _async_probe_installation(self) -> None:
        """Look for circuits the heating system has gained or lost.

        A circuit added to the plumbing answers where it used to 404. Probing
        for that costs about thirty requests, which is why it happens hourly
        rather than every minute.

        A failed probe is not a failed poll: knowing nothing new about the
        installation is no reason to drop the readings the user is watching,
        so the error is logged and the known installation kept.
        """
        self._probed_at = dt_util.utcnow()
        try:
            installation = await self.client.async_discover_installation(
                include_zones=False, include_devices=False
            )
        except K40Error as err:
            _LOGGER.debug("Installation probe failed, keeping what is known: %s", err)
            return

        if installation == self.installation:
            return

        # Only the ids that are new have to be probed for presence; what was
        # there a minute ago is there still, and re-reading all of it would
        # double the poll it is running inside.
        expanded = candidates_for(installation)
        known = {candidate.path for candidate in self.candidates}
        fresh = [candidate for candidate in expanded if candidate.path not in known]
        present = (
            set(await self._fetch([candidate.path for candidate in fresh])) if fresh else set()
        )

        self.installation = installation
        # Dropping a vanished circuit's paths is not the same as removing its
        # device: the entities stay and go unavailable, and the device is only
        # removed on the next reload, where a completed discovery vouches for
        # its absence.
        self.candidates = [c for c in expanded if c.path in known or c.path in present]
        self._paths = [c.path for c in self.candidates]

        _LOGGER.info(
            "Installation changed: now %s resources across %s heat source(s), "
            "%s heating circuit(s), %s hot water circuit(s)",
            len(self._paths),
            len(installation.heat_sources),
            len(installation.heating_circuits),
            len(installation.dhw_circuits),
        )
        self._rebuild_runtime()

    def _rebuild_runtime(self) -> None:
        """Rebuild what the platforms read off, so new entities can be made."""
        runtime = self.config_entry.runtime_data
        runtime.signal_coordinator.set_signals(self.installation.signals)
        runtime.devices = build_device_tree(
            runtime.gateway_id,
            runtime.system_info,
            self.installation,
            runtime.hub,
            runtime.hub_device_id,
        )


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
