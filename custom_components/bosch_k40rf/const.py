"""Constants for the Bosch K 40 RF integration."""

from __future__ import annotations

from datetime import timedelta
from typing import Final

DOMAIN: Final = "bosch_k40rf"

MANUFACTURER: Final = "Bosch"

CONF_TOKEN: Final = "token"
CONF_DEVICE_ID: Final = "device_id"

#: Ports are stored per entry rather than assumed: the gateway publishes both
#: in its mDNS record, and a discovered gateway may not use the defaults.
CONF_AUTH_PORT: Final = "auth_port"

#: Live readings. The gateway answers each resource with its own request, so a
#: poll is dozens of round trips against a small embedded device. Sixty seconds
#: keeps that load modest while still tracking a heat pump's behaviour, which
#: moves over minutes rather than seconds.
SCAN_INTERVAL: Final = timedelta(seconds=60)

#: Diagnostic signals change slowly and are disabled by default, so they are
#: polled on their own, much slower schedule.
SIGNAL_SCAN_INTERVAL: Final = timedelta(minutes=10)

#: How many resources to ask for at once during a poll.
MAX_CONCURRENT_REQUESTS: Final = 4

DATA_GATEWAY_ID: Final = "gateway_id"
