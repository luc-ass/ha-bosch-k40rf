# Bosch K 40 RF for Home Assistant

Reads a Bosch Connect-Key **K 40 RF** heating gateway over its local API. Works
for Buderus-branded systems too. Everything is read-only: the device API offers
nothing else.

Requires gateway firmware **15.00.01** or newer.

> [!WARNING]
> **Beta — version 0.1.0.**
>
> This has been exercised against exactly one heating system: an air-to-water
> heat pump with one heating circuit, one hot water circuit and mechanical
> ventilation. Everything else follows the published API but has never met real
> hardware.
>
> Expect rough edges. Entity names and unique IDs may still change between
> releases, and a changed unique ID means the entity is recreated and its
> history starts over. Do not build anything you depend on for heating on top
> of this yet.
>
> Problem reports are the most useful thing you can contribute — especially
> from systems with solar, a pool, several heating circuits or a cascade of
> heat sources. Please attach the diagnostics download; it is redacted.

> [!NOTE]
> **Not affiliated with Bosch.**
>
> This is an independent, community-built project. It is not affiliated with,
> endorsed by, supported by or otherwise connected to Bosch Thermotechnik GmbH,
> the Bosch Home Comfort Group, or Buderus. "Bosch", "Buderus" and
> "Connect-Key" are trademarks of their respective owners and appear here only
> to say which hardware this software talks to.
>
> It is built against the OpenAPI description Bosch publishes at
> [bosch-home-comfort/api-docs](https://github.com/bosch-home-comfort/api-docs)
> (Apache-2.0), extended by what a live gateway reports for the `/signals`
> branch, which that description does not cover. No firmware was modified and
> nothing is bypassed: the gateway hands out the access token itself, to
> whoever can press its buttons.
>
> Using it is at your own risk. See [LICENSE](LICENSE).

## What you get

- Temperatures, pressures, flow rates, modulation and status across the heat
  source, heating circuits, hot water and ventilation
- Energy counters split by component (produced, compressor, electric heater,
  ventilation), so the energy dashboard and a performance-factor template both
  work. Start counts and working times are split the same way, and keep their
  own units rather than being mislabelled as energy
- Around 90 diagnostic signals, off by default
- Discovery: the gateway announces itself, so setup only asks for the sticker
  password

## Install (HACS)

1. Add `https://github.com/luc-ass/ha-bosch-k40rf` as a custom repository.
2. Install **Bosch K 40 RF** and restart Home Assistant.
3. The gateway should appear under discovered devices. If not, add it manually
   with its IP address.
4. Enter the login and password from the sticker on the Connect-Key module.
5. When asked, **press the WLAN and radio buttons on the gateway together for
   about a second**, until the blue LED lights up, then continue.

### If pairing keeps failing

The gateway only issues a token to a client on its own subnet, and only within
about five minutes of the buttons being pressed. Both conditions have to hold.
If Home Assistant runs elsewhere -- a different VLAN, a routed VPN -- pairing
can never succeed from there. Obtain a token from a machine on the gateway's
network and paste it into the optional field on the last step.

The token does not expire, and reading data afterwards works from anywhere.

## How it decides what to create

The published API declares 261 paths, covering every installation variant Bosch
sells: up to six heat sources, four heating circuits, solar, pool, sixteen
zones. No single house has all of them, and the ones it does not have answer
404.

So the integration declares all of them and asks once at startup which ones
answer. Only those become entities and only those get polled. A cascade of
three heat sources or a solar circuit is handled by the same code that handles
a single air-to-water heat pump -- it just finds more.

A circuit added to your heating system later is picked up when the integration
reloads, not while it is running. One that is taken out loses its device on the
next reload.

## How it groups what it creates

The gateway becomes the hub device, and each circuit, zone and heat source it
reports becomes a device of its own beneath it:

```
K 40 RF                     gateway diagnostics, plant-wide system readings
|-- Compress CS5800iAW      the heat generator
|-- Heating circuit         one per circuit, numbered where there are several
|-- Hot water
`-- Ventilation
```

The functional branches of the API decide this, because they are what every
installation reports. `/system/basicInfo` lists the physical modules with their
product name, firmware and serial number, but it does not say which module
serves which branch -- so it is used to enrich a device, never to invent one. A
product name is claimed for a heat source only where there is exactly one; a
cascade gets numbered heat sources and no guessed models.

Readings that describe the plant rather than one circuit -- outdoor
temperature, system pressure, the energy balance of a cascade -- stay on the
gateway.

Entity names say what the device does not: on "Heating circuit" the room
temperature is "Room temperature", not "Heating circuit room temperature". The
diagnostic signals are named the same way, from their controller id minus the
part the device already carries -- `VENTILATION.FrostProt.PreHeatPower` reads
as "Frost protection pre heat power" on the ventilation unit. Acronyms the API
never spells out (`RTSD`, `FPD`, `CUHP`) are left as the controller writes
them, because a guess would read better and mean less.

## Polling

Live readings every 60 seconds, diagnostic signals every 10 minutes and only
while at least one of them is enabled. The gateway serves one resource per
request, so a poll is dozens of small requests; at most four run at a time.

History (`/recordings`) is not polled at all.

## Tested installations

The integration declares every resource Bosch's spec describes -- 204 of them --
but only **101 have ever answered on real hardware**, all of it the same
installation. The rest is written against the spec, and the spec has been wrong
twice already.

| Appliance | System | Circuits | Firmware | Confirmed |
|---|---|---|---|---|
| Compress CS5800iAW 12 MB + AW 12 OR-T | `heatpump_single`, EMS2.0 | hs1, hc1, dhw1, ventilation zone1 | 15.00.01 | 101 resources, 87 signals |

**If your system is not in this table, a diagnostics file from it is the most
useful thing you can send** -- particularly a cascade, solar, a pool, a gas or
oil boiler, several heating circuits, zones with radio thermostats, or a
Buderus-branded system.

Settings -> Devices & services -> Bosch K 40 RF -> ... -> **Download
diagnostics**, then open an [installation
report](https://github.com/luc-ass/ha-bosch-k40rf/issues/new?template=installation_report.yml).
The file leaves out your token, gateway id and serial numbers; it does contain
your heating readings, so have a look before attaching it.

What happens to it: `tools/report_from_diagnostics.py` turns the file into a
list of what your system confirms that ours never had, what it serves that the
catalogue does not declare, and what its `/signals` branch looks like. That
usually becomes a commit the same day, and your system joins the table.

## Known limitations

- **Read-only.** Every field the device exposes is marked non-writable, so
  there are no climate or water-heater entities, and no actions. In Bosch's own
  API discussion a maintainer wrote that "write access for the Local API is
  definitely on our radar for the future" and that a web API with write access
  is planned "in the coming months", with safeguards and no date
  ([discussion](https://github.com/bosch-home-comfort/api-docs/discussions/2), 16 Sep 2026). Nothing to build on yet, but the shape of
  this integration -- all API calls in `pyk40rf`, entities derived from the
  spec -- is what makes adding writable entities a small change rather than a
  rewrite.
- **One installation tested.** Solar, pool, cascade, several circuits and
  radio thermostats follow the spec but have never met hardware -- see [Tested
  installations](#tested-installations) for what a report needs.
- Historical data is available from the API but is not yet imported into
  long-term statistics.

## Differences from the Home Assistant Core version

This repository is the HACS build. Two things differ from what a Core
submission carries:

| | HACS (here) | Core |
|---|---|---|
| `manifest.json` → `documentation` | this repository | `home-assistant.io/integrations/bosch_k40rf` |
| `manifest.json` → `version` | required | must be absent |
| `manifest.json` → `requirements` | `pyk40rf@git+https://github.com/luc-ass/pyk40rf@v0.1.3` | `pyk40rf==0.1.x`, from PyPI |
| Brand images | `custom_components/bosch_k40rf/brand/` | PR to `home-assistant/brands` |

`pyk40rf` is not on PyPI yet, so the integration pulls it from its GitHub tag.
Core requires a PyPI release (`dependency-transparency`), so that line has to
change before submission.

## Development

```bash
pytest
ruff check custom_components tests
mypy custom_components/bosch_k40rf
python -m script.hassfest --integration-path .../custom_components/bosch_k40rf
```

The resource catalogue and the entity names in `strings.json` are generated:

```bash
python tools/generate_catalog.py    # from the API spec + a live harvest
python tools/generate_strings.py    # entity names, from the catalogue
```

A diagnostics file from somebody else's heating system is read with:

```bash
python tools/report_from_diagnostics.py diagnostics.json
```

It says what that installation confirms, what it serves that the catalogue does
not declare, and what its `/signals` branch looks like. Newly confirmed
resources belong in the catalogue as `live_confirmed`, which
`generate_catalog.py` writes from a harvest.

## License

Apache-2.0
