![Bosch K 40 RF and Buderus MX400 — Home Assistant integration via local API](https://raw.githubusercontent.com/luc-ass/ha-bosch-k40rf/main/images/banner.webp)

# Bosch K 40 RF / Buderus MX 400 for Home Assistant

Reads a Bosch Connect-Key **K 40 RF** heating gateway over its local API — the
one the gateway serves on your own network, with a token it hands out itself.
Buderus-branded systems use the same module, work the same way, and are named
as the Buderus hardware they are.

Everything is read-only. That is the device's decision, not this integration's:
every field it exposes is marked non-writable.

**Requires gateway firmware 15.00.01 or newer.** Older firmware has no local
API at all.

> [!WARNING]
> **Beta — version 0.1.14.**
>
> Three heating systems have ever run this, all air-to-water heat pumps: the
> development system, which also has hot water and mechanical ventilation, a
> Buderus Logatherm with neither, and one with a second, mixed heating circuit.
> Everything else — cascades, solar, pools, gas and oil boilers, radio zones —
> follows Bosch's published spec and has never met hardware.
>
> Expect rough edges, and expect entity **names** to keep changing while the
> shape of things settles. Entity and device **identities** have been stable
> since 0.1.4: a renaming changes what you read, not what your automations point
> at, and your history carries over.
>
> Do not build anything your heating depends on on top of this yet.

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

- **Temperatures, pressures, flow rates, modulation and status** across the
  heat generator, the heating circuits, hot water and ventilation — grouped
  into one device per circuit, rather than one page with everything on it.
- **Energy counters split by component** (produced, compressor, electric
  heater, ventilation), so the energy dashboard works and a performance factor
  is one template division. Start counts and working times arrive in the same
  shape and keep their own units instead of being mislabelled as energy.
- **Diagnostic signals from the controller itself** — compressor speed, valve
  positions, frost protection, bus status. How many there are is the
  appliance's decision, not ours: of the three systems tested, they serve 87,
  99 and 119. About half are flags, and those are binary sensors rather than
  text reading the word "true", so an automation says `is_on`. Disabled by
  default; switch on the ones you want.
- **A circuit fitted later turns up by itself.** The installation is probed
  again once an hour, so a second heating circuit gets its device and its
  entities without a restart. One that stops answering goes unavailable and
  stays: a module without power looks exactly like one that was removed, so
  deleting it is a button on its device page rather than something that
  happens to you.
- **Faults read as "unknown", not as −3276.8 °C.** The gateway reports a broken
  sensor as a sentinel value; those are recognised instead of charted.

## Install

Through [HACS](https://hacs.xyz):

1. Add `https://github.com/luc-ass/ha-bosch-k40rf` as a custom repository
   (type: integration).
2. Install **Bosch K 40 RF**, then restart Home Assistant.
3. **Settings → Devices & services → Add integration → Bosch K 40 RF**, and
   enter the gateway's IP address.
4. Choose **Pair with the device password**.
5. Enter the login and password from the sticker on the Connect-Key module.
6. When asked, **press the WLAN and radio buttons on the gateway together for
   about a second**, until the blue LED lights up, then continue.

The other branch, **Enter an existing token**, asks for nothing but a token —
see [below](#if-pairing-keeps-failing). Take it if Home Assistant cannot reach
the gateway's own network, or if you would rather obtain and rotate the token
yourself: the token is the only credential the integration ever stores, and the
sticker password is never written to disk either way.

The gateway also announces itself over mDNS (`_hvac-open-api._tcp`) and the
integration listens for that. At the one installation available for testing the
announcement only turned up *after* the gateway had been addressed once by IP —
so if it is not offered to you, add it by address; that may well be what makes
it appear. A gateway found that way keeps its address current by itself; one
added by hand is corrected under **Settings → Devices & services → Bosch K 40 RF
→ Reconfigure**.

### If pairing keeps failing

The gateway issues a token only to a client **on its own subnet**, and only
within about five minutes of the buttons being pressed. Both conditions have to
hold, and both failures report the same error.

If Home Assistant runs elsewhere — a different VLAN, a routed VPN — pairing can
never succeed from there. Get the token yourself from any machine on the
gateway's network, and choose **Enter an existing token** in the setup dialogue.
The same choice is offered when a stored token stops working, so a token you
rotate yourself can be handed in again.

Press the WLAN and radio buttons together for about a second, then, within the
next few minutes:

```bash
curl --insecure --request POST \
  "https://192.0.2.10:9442/auth/token" \
  --header "Content-Type: application/x-www-form-urlencoded" \
  --data-urlencode "grant_type=password" \
  --data-urlencode "username=123456789" \
  --data-urlencode "password=aaaabbbbccccdddd" \
  --data-urlencode "client_name=home-assistant"
```

`username` and `password` are the login and password from the sticker on the
Connect-Key module — the login is the gateway's nine-digit id — **with the
dashes of the password removed**. `--insecure` is needed because the gateway
serves a self-signed certificate whose name is that numeric id rather than a
hostname; the connection never leaves your own network. Replace `192.0.2.10`
with the gateway's address.

The answer carries the token:

```json
{"access_token": "eyJhbGciOi...", "token_type": "Bearer"}
```

`412 physical_proximity_unproven` means one of the two conditions did not hold
— the buttons were not pressed recently enough, or the request did not come
from the gateway's own subnet. Both report the same error, so check both.

To confirm the token works before pasting it (reading has no subnet
restriction, so this one can be run from anywhere):

```bash
curl --insecure --header "Authorization: Bearer <access_token>" \
  "https://192.0.2.10:9443/gateway/versionFirmware"
```

The token does not expire, several tokens can be valid at once, and reading data
afterwards works from anywhere.

## How it works

### What it creates

Bosch's spec declares every installation the K 40 RF can sit in front of: up to
six heat sources, four heating circuits, solar, pool, sixteen zones. No house
has all of it, and the parts a gateway does not have answer `404`.

So the integration declares all of them — 204 resources — and asks once at
startup which ones answer. Only those become entities, and only those get
polled. A cascade of three heat sources or a solar circuit runs through the same
code as a single heat pump; it simply finds more.

A circuit added to your heating system later appears when the integration
reloads, not while it is running. One taken out loses its device on the next
reload.

### How it groups them

The gateway is the hub, and every circuit, zone and heat source it reports
becomes a device beneath it:

```
K 40 RF                     gateway diagnostics, plant-wide readings
├── Compress CS5800iAW      the heat generator
├── Heating circuit         one per circuit, numbered where there are several
├── Hot water
└── Ventilation
```

The functional branches of the API decide this, because they are the one thing
every installation reports. `/system/basicInfo` lists the physical modules with
product name, firmware and serial number, but never says which module serves
which branch — so it enriches a device and never invents one. A product name is
claimed for a heat generator only where there is exactly one; a cascade gets
numbered heat sources and no guessed models.

Readings that describe the plant rather than one circuit — outdoor temperature,
system pressure, the energy balance of a cascade — stay on the gateway.

The gateway is named after the brand it reports. `/gateway/brand` answers Bosch
on one installation and Buderus on the next, and the module names itself K40RF
or MX400 to match, so a Buderus system gets an **MX 400** with Buderus as the
manufacturer on every device under it.

### What things are called

The device says what the entity then does not: on "Heating circuit" the room
temperature is **Room temperature**, not "Heating circuit room temperature".

The diagnostic signals are named from their controller id, minus the part the
device already carries: `VENTILATION.FrostProt.PreHeatPower` reads as **Frost
protection pre heat power** on the ventilation unit. Acronyms the API never
spells out — `RTSD`, `FPD`, `SD`, `CUHP` — are left exactly as the controller
writes them, because a guessed expansion would read better and mean less.

### Polling

Live readings every 60 seconds. Diagnostic signals every 10 minutes, and only
while at least one of them is enabled — the first one enabled is read at once
rather than at the next interval, so a signal switched on has a value within
seconds. The gateway serves one resource per request, so a poll is dozens of
small requests; at most four run at a time.

A signal's unit and its label table come from the reading, not from a
catalogue: `SRC.OutdoorTemp` is a temperature in °C with a history, and
`SC.SeasonOpt.Mode` an enumeration that reads **HEATING**. The controller's
own lifetime counters — everything under a `Stats` segment — are totals rather
than momentary readings, while a `Timer` counts down and is not. The three
parts of `SC.InstallationDate` are a date, so they are charted as nothing at
all.

If you had flag signals enabled before 0.1.15, they were sensors reading the
word "true"; the sensors are removed on upgrade and the binary sensors arrive
disabled, so switch the ones you want back on. A rename or an area you had set
on one of them is lost with it.

Which signals are **flags** cannot come from the reading, because the entity
has to exist before the branch is ever polled — and it is not polled at all
while every one of its entities is disabled, which is the normal case. So that
one comes from a list built out of the installations people have sent in. A
flag the list does not know stays a sensor reading "true", and the log names it
once per start so the next report can fix it.

History (`/recordings`) is available from the API but is not polled, and not
imported into long-term statistics.

## Tested installations

204 resources are declared and **104 have ever answered on real hardware**,
across three installations. The rest is written against the spec, and the
spec is not a safe assumption: of the 100 paths that could be compared against
a live device, **21 disagreed with it** — a unit written `rpm"`, a JSON boolean
inside a `stringValue`, an enum differing in case, sensor-fault sentinels that
appear in no example. The enumerations and units live only in the spec's
examples, which nothing validates, and they have drifted from the firmware.

| Appliance | System | Circuits | Firmware | Confirmed |
|---|---|---|---|---|
| Compress CS5800iAW 12 MB + AW 12 OR-T | `heatpump_single`, EMS 2.0 | hs1, hc1, dhw1, ventilation zone1 | 15.00.01 | 101 resources, 87 signals |
| Buderus Logatherm WLW186i-12 TP70 + WLW MB-5 AR | `heatpump_single`, EMS 2.0 | hs1, hc1 | 15.00.01 | 65 resources, 99 signals |
| Compress CS5800iAW 12 MB + AW 10 OR-T | `heatpump_single`, EMS 2.0 | hs1, hc1, **hc2**, dhw1 | 15.00.01 | 78 resources, 120 signals |

The second one ([#2](https://github.com/luc-ass/ha-bosch-k40rf/issues/2)) shows
what such a file is worth. It added two resources nobody had ever seen answer,
which is the small half. The other half: 31 controller signals that do not
exist on the first machine, the fact that every field is non-writable on a
gateway that is not ours, and a bug in how two heating-circuit setpoints were
read — which would have gone unnoticed until the first cold day.

The third ([discussion #1](https://github.com/luc-ass/ha-bosch-k40rf/discussions/1))
is the first **second heating circuit** this code has ever met, and it is a
mixed one: it reports a mixer position, a separate maximum flow temperature,
and three signals from the mixer module itself under a head segment — `HC2MOD.*`
— that appears on no other machine and used to leave those readings on the
gateway. It also found a bug worth more than any of that: with EEBUS
commissioned, one field answers with raw bytes inside a JSON string, and a
single unreadable field used to cost the whole poll. All 120 of this
installation's signals were lost to it.

Its **second** file, sent after that fix shipped, is what made the flags
visible: 119 signals with values rather than 120 bare ids, and 52 of them
reading the words "true" or "false" at a sensor that could only show them as
text. A file from a system that already works is worth this much.

**If your system is not in this table, its diagnostics file is the most useful
thing you can send** — particularly a cascade, solar, a pool, a gas or oil
boiler, several heating circuits, or zones with radio thermostats.

**Settings → Devices & services → Bosch K 40 RF → ⋯ → Download diagnostics**,
then either open an [installation
report](https://github.com/luc-ass/ha-bosch-k40rf/issues/new?template=installation_report.yml)
or, if nothing is actually wrong, post it in
[Discussions](https://github.com/luc-ass/ha-bosch-k40rf/discussions) — a file
from a system that simply works is worth exactly as much.

The file leaves out your token, your gateway id, the serial numbers and the
gateway's MAC addresses. It does contain your heating readings — temperatures,
energy counters, which circuits exist — and the gateway's address on your own
network. Have a look before attaching it.

What happens to it: `tools/report_from_diagnostics.py` turns it into a list of
what your system confirms that ours never had, what it serves that the
catalogue does not declare, and what its `/signals` branch looks like. That is
usually a commit the same day, and your system joins the table.

## Known limitations

- **Read-only.** No climate, water-heater or switch entities, and no actions.
  In Bosch's own API discussion a maintainer wrote that "write access for the
  Local API is definitely on our radar for the future", and that a web API with
  write access is planned "in the coming months", with safeguards and no date
  ([discussion](https://github.com/bosch-home-comfort/api-docs/discussions/2),
  16 Sep 2026). Nothing to build on yet — but every API call lives in
  [`pyk40rf`](https://github.com/luc-ass/pyk40rf) and every entity is derived
  from the spec, so writable entities would be an addition rather than a
  rewrite.
- **Two installations tested**, both single-circuit air-to-water heat pumps.
  See [Tested installations](#tested-installations).
- **Discovery is unreliable.** The announcement has been seen, but only after
  the gateway had been contacted once over its API. Cause unknown; manual setup
  always works.
- **Pairing needs physical access and the same subnet.** There is no remote path
  to a first token.
- **No history import.** The gateway keeps hourly, daily and monthly series;
  statistics here start the day you set the integration up.
- **Entity names are English.** German covers the setup dialogue and the device
  names only.

## Differences from the Home Assistant Core version

This repository is the HACS build. What a Core submission carries differs in
four places:

| | HACS (here) | Core |
|---|---|---|
| `manifest.json` → `documentation` | this repository | `home-assistant.io/integrations/bosch_k40rf` |
| `manifest.json` → `version` | required | must be absent |
| `manifest.json` → `issue_tracker` | required by HACS | must be absent |
| Brand images | `custom_components/bosch_k40rf/brand/` | PR to `home-assistant/brands` |

The dependency is the same in both: `pyk40rf==0.1.6` from PyPI, built from
source by the library's own release workflow.

## Development

```bash
pytest
ruff check custom_components tools tests
mypy custom_components/bosch_k40rf
python -m script.hassfest --integration-path .../custom_components/bosch_k40rf
```

Three files are generated and must not be hand-edited; the rules behind the
names live in `naming.py` and feed the first two:

```bash
python tools/generate_catalog.py    # catalog.py, from the API spec + a live harvest
python tools/generate_strings.py    # strings.json + translations/en.json
python tools/quality_report.py      # QUALITY.md, from quality_scale.yaml
```

[`QUALITY.md`](QUALITY.md) is where the integration stands against Home
Assistant's quality scale, and what each open rule still needs.

Somebody else's diagnostics file is read with:

```bash
python tools/report_from_diagnostics.py diagnostics.json
```

Newly confirmed resources belong in the catalogue as `live_confirmed`, which
`generate_catalog.py` writes from a harvest.

Two rules the tests enforce, both learned the hard way:

- **Nothing is declared by hand that the spec already declares.** Four invented
  probe paths once took a running installation down, because the gateway answers
  `403` — not `404` — for anything outside its spec.
  (`tests/test_resources.py::TestProbePaths`)
- **No two entities of one device may read the same.** That check found two name
  collisions that had been invisible while every entity sat on one page.
  (`tests/test_resources.py::TestNaming::test_names_are_unique_per_device`)

## License

Apache-2.0 — see [LICENSE](LICENSE).
