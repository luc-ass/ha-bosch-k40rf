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
reloads, not while it is running.

## Polling

Live readings every 60 seconds, diagnostic signals every 10 minutes and only
while at least one of them is enabled. The gateway serves one resource per
request, so a poll is dozens of small requests; at most four run at a time.

History (`/recordings`) is not polled at all.

## Known limitations

- **Read-only.** Every field the device exposes is marked non-writable, so
  there are no climate or water-heater entities, and no actions.
- Developed against one installation (air-to-water heat pump, one heating
  circuit, mechanical ventilation with heat recovery). Solar, pool and cascade
  setups follow the spec but are untested -- reports welcome.
- Historical data is available from the API but is not yet imported into
  long-term statistics.

## Differences from the Home Assistant Core version

This repository is the HACS build. Two things differ from what a Core
submission carries:

| | HACS (here) | Core |
|---|---|---|
| `manifest.json` → `documentation` | this repository | `home-assistant.io/integrations/bosch_k40rf` |
| `manifest.json` → `version` | required | must be absent |
| `manifest.json` → `requirements` | `pyk40rf@git+https://github.com/luc-ass/pyk40rf@v0.1.0` | `pyk40rf==0.1.0`, from PyPI |
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

## License

Apache-2.0
