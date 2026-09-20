"""How resources are grouped into devices.

The registry-level test lives in test_init; these cover the rules that only
another installation would exercise -- a cascade, several circuits, a gateway
whose modules say nothing useful.
"""

from __future__ import annotations

from pyk40rf import Installation, SystemInfo, SystemInfoModule
import pytest

from custom_components.bosch_k40rf.catalog import ResourceSpec
from custom_components.bosch_k40rf.const import DOMAIN
from custom_components.bosch_k40rf.devices import DeviceTree, build_device_tree, build_hub
from custom_components.bosch_k40rf.naming import signal_name
from custom_components.bosch_k40rf.resources import ResourceCandidate

from .conftest import DEVICE_ID

HUB_DEVICE_ID = "abcdef"


def tree(system_info: SystemInfo, installation: Installation) -> DeviceTree:
    """Build the device tree the way the integration does at setup."""
    hub = build_hub(DEVICE_ID, system_info, firmware="15.00.01")
    return build_device_tree(DEVICE_ID, system_info, installation, hub, HUB_DEVICE_ID)


def candidate(path: str, circuit_id: str | None = None) -> ResourceCandidate:
    """Return a catalogue entry as the resource expansion hands it to a platform."""
    return ResourceCandidate(
        path=path, spec=ResourceSpec(path=path, value_type="floatValue"), circuit_id=circuit_id
    )


def test_the_gateway_is_the_hub(system_info: SystemInfo, installation: Installation) -> None:
    hub = tree(system_info, installation).hub
    assert hub["identifiers"] == {(DOMAIN, DEVICE_ID)}
    assert hub["model"] == "K 40 RF"
    assert hub["sw_version"] == "15.00.01"
    assert "via_device_id" not in hub


#: What /system/basicInfo lists on a Buderus installation: the same gateway,
#: reporting itself as MX400 rather than K40RF. From the diagnostics of a
#: Logatherm WLW186i-12 TP70 (issue #2).
BUDERUS_SYSTEM_INFO = SystemInfo(
    gateway_id=DEVICE_ID,
    modules=(
        SystemInfoModule(
            name="Logatherm WLW186i-12 TP70",
            hardware_id="XCU_THH",
            version="12.11.1-2fc97779",
            serial_number="4" * 23,
        ),
        SystemInfoModule(
            name=None,
            hardware_id="HMI_module_02_800-20_GSBS_BU_111x",
            version="47.12-FIELD",
            serial_number=None,
        ),
        SystemInfoModule(
            name=None, hardware_id="MX400", version="15.00.01", serial_number="5" * 23
        ),
        SystemInfoModule(
            name="Logatherm WLW MB-5 AR",
            hardware_id="XCU_SRH",
            version="9.16.0-dab9f463",
            serial_number="6" * 23,
        ),
    ),
)


class TestBrand:
    """One gateway, several brands: what /gateway/brand says decides."""

    def test_the_reported_brand_is_the_manufacturer(self, system_info: SystemInfo) -> None:
        hub = build_hub(DEVICE_ID, system_info, brand="Bosch")
        assert hub["manufacturer"] == "Bosch"

    def test_a_buderus_gateway_is_not_called_a_bosch(self) -> None:
        hub = build_hub(DEVICE_ID, BUDERUS_SYSTEM_INFO, brand="Buderus")
        assert hub["manufacturer"] == "Buderus"
        assert hub["model"] == "MX 400"
        assert hub["name"] == "MX 400"
        assert hub["model_id"] == "MX400"

    def test_the_gateway_module_is_found_under_either_name(self) -> None:
        """The module carries the firmware, and its id differs per brand."""
        hub = build_hub(DEVICE_ID, BUDERUS_SYSTEM_INFO, brand="Buderus")
        assert hub["sw_version"] == "15.00.01"

    def test_the_branches_carry_the_brand_too(self, installation: Installation) -> None:
        hub = build_hub(DEVICE_ID, BUDERUS_SYSTEM_INFO, brand="Buderus")
        devices = build_device_tree(
            DEVICE_ID, BUDERUS_SYSTEM_INFO, installation, hub, HUB_DEVICE_ID
        )
        device = devices.for_resource("/heatingCircuits/hc1/maxFlowTemp", "hc1")
        assert device["manufacturer"] == "Buderus"

    def test_an_unreported_brand_falls_back(self, system_info: SystemInfo) -> None:
        """A gateway that answers no brand is still overwhelmingly a Bosch."""
        hub = build_hub(DEVICE_ID, system_info)
        assert hub["manufacturer"] == "Bosch"
        assert hub["model"] == "K 40 RF"


def test_the_appliance_names_its_heat_source(
    system_info: SystemInfo, installation: Installation
) -> None:
    """One heat source, so the module carrying a product name has to be it."""
    device = tree(system_info, installation).for_resource("/heatSources/hs1/workingTime", "hs1")
    assert device["name"] == "Compress CS5800iAW 12 MB"
    assert device["model"] == "Compress CS5800iAW 12 MB"
    assert device["sw_version"] == "9.7.0"
    assert device["via_device_id"] == HUB_DEVICE_ID


def test_a_plant_wide_heat_source_reading_joins_the_only_heat_source(
    system_info: SystemInfo, installation: Installation
) -> None:
    """/heatSources/actualSupplyTemperature names no id but describes hs1."""
    devices = tree(system_info, installation)
    assert devices.for_resource("/heatSources/actualSupplyTemperature") == devices.for_resource(
        "/heatSources/hs1/workingTime", "hs1"
    )


def test_a_cascade_leaves_plant_wide_readings_on_the_gateway(
    system_info: SystemInfo,
) -> None:
    """With six heat sources, an unqualified reading belongs to no single one."""
    devices = tree(system_info, Installation(heat_sources=("hs1", "hs2")))
    assert devices.for_resource("/heatSources/actualSupplyTemperature") == devices.hub


def test_a_cascade_claims_no_product_name(system_info: SystemInfo) -> None:
    """``/system/basicInfo`` never says which module is which heat source."""
    devices = tree(system_info, Installation(heat_sources=("hs1", "hs2")))
    first = devices.for_resource("/heatSources/hs1/workingTime", "hs1")
    assert first["model"] is None
    assert first["translation_key"] == "heat_source_numbered"
    assert first["translation_placeholders"] == {"number": "1"}


def test_several_circuits_are_numbered(system_info: SystemInfo) -> None:
    devices = tree(system_info, Installation(heating_circuits=("hc1", "hc2")))
    second = devices.for_resource("/heatingCircuits/hc2/roomtemperature", "hc2")
    assert second["translation_key"] == "heating_circuit_numbered"
    assert second["translation_placeholders"] == {"number": "2"}


def test_a_single_circuit_is_not_numbered(
    system_info: SystemInfo, installation: Installation
) -> None:
    device = tree(system_info, installation).for_resource(
        "/heatingCircuits/hc1/roomtemperature", "hc1"
    )
    assert device["translation_key"] == "heating_circuit"
    assert "translation_placeholders" not in device


def test_the_ventilation_module_is_recognised(
    system_info: SystemInfo, installation: Installation
) -> None:
    """MV200 is the only module that looks like ventilation hardware."""
    device = tree(system_info, installation).for_resource(
        "/ventilation/zone1/supplyFanPower", "zone1"
    )
    assert device["sw_version"] == "53.03"


def test_a_module_id_is_not_passed_off_as_a_model(
    system_info: SystemInfo, installation: Installation
) -> None:
    """MV200 is the module inside the unit; the unit is sold as a Vent 5000 C."""
    device = tree(system_info, installation).for_resource(
        "/ventilation/zone1/supplyFanPower", "zone1"
    )
    assert device["model_id"] == "MV200"
    assert device["model"] is None


def test_a_product_name_is_shown_as_the_model(
    system_info: SystemInfo, installation: Installation
) -> None:
    """The appliance does name itself, so that name is a model, not an id."""
    device = tree(system_info, installation).for_resource("/heatSources/hs1/workingTime", "hs1")
    assert device["model"] == "Compress CS5800iAW 12 MB"
    assert device["model_id"] == "XCU_THH"


@pytest.mark.parametrize(
    ("signal", "expected"),
    [
        # Real signal ids from the test installation.
        ("VENTILATION.FrostProt.PreHeatPower", "ventilation"),
        ("VENTILATION.BasicFunction.VENT1.SupFanLevel", "ventilation"),
        ("SC.HC1.FlowTempSetp", "heatingCircuits"),
        ("SC.HC1.RTSD.CurrentRoomTempSetp", "heatingCircuits"),
        ("SC.DHW1.SD.ExtraActive", "dhwCircuits"),
        ("SRC.CUHP.HP1.CompressorSpeedActual", "heatSources"),
        ("SRC.OutdoorTemp", "heatSources"),
        # The heat pump's own hot-water block, not the hot water circuit's.
        ("SRC.CUHP.DHW.ExternBlocked", "heatSources"),
        # Likewise: the heat pump drives the circuit pump, and says so.
        ("SRC.CUHP.CH.HC1PumpRelay", "heatSources"),
        # The system controller and the bus have no device of their own.
        ("SC.SeasonOpt.Mode", None),
        ("SC.DampOutdTemp", None),
        ("GWEEBUS.Status", None),
    ],
)
def test_a_signal_joins_the_device_its_name_points_at(
    system_info: SystemInfo, installation: Installation, signal: str, expected: str | None
) -> None:
    devices = tree(system_info, installation)
    target = devices.for_signal(f"/signals/{signal}")
    if expected is None:
        assert target == devices.hub
    else:
        circuit = {"heatSources": "hs1", "heatingCircuits": "hc1"}.get(
            expected, {"dhwCircuits": "dhw1", "ventilation": "zone1"}.get(expected, "")
        )
        assert target == devices.for_resource(f"/{expected}/{circuit}/x", circuit)


def test_a_cascade_leaves_an_unnumbered_signal_on_the_gateway(system_info: SystemInfo) -> None:
    """SRC.OutdoorTemp names no heat source, so with several it names none."""
    devices = tree(system_info, Installation(heat_sources=("hs1", "hs2")))
    assert devices.for_signal("/signals/SRC.OutdoorTemp") == devices.hub
    # A numbered one still lands where it says.
    assert devices.for_signal("/signals/SRC.CUHP.HP2.ReturnTemp") == devices.for_resource(
        "/heatSources/hs2/workingTime", "hs2"
    )


def test_a_mixer_module_joins_the_circuit_it_drives(system_info: SystemInfo) -> None:
    """Seen on a two-circuit Bosch CS5800iAW (discussion #1).

    A mixed circuit is driven by its own module, and that module heads its
    signals itself -- HC2MOD.FlowTemp -- instead of hanging them under the
    system controller. They still report on hc2.
    """
    devices = tree(system_info, Installation(heating_circuits=("hc1", "hc2")))
    hc2 = devices.for_resource("/heatingCircuits/hc2/maxFlowTemp", "hc2")
    for signal in ("HC2MOD.FlowTemp", "HC2MOD.FlowCtrl.MixerPosition"):
        assert devices.for_signal(f"/signals/{signal}") == hc2
    # Without that circuit there is no device to join, and the name has to
    # keep saying which one it meant.
    lone = tree(system_info, Installation(heating_circuits=("hc1",)))
    assert lone.for_signal("/signals/HC2MOD.FlowTemp") == lone.hub


def test_a_signal_for_a_circuit_this_house_lacks_stays_on_the_gateway(
    system_info: SystemInfo, installation: Installation
) -> None:
    devices = tree(system_info, installation)
    assert devices.for_signal("/signals/SC.HC4.FlowTempSetp") == devices.hub


@pytest.mark.parametrize(
    "path",
    [
        "/gateway/versionFirmware",
        "/system/sensors/temperatures/outdoor_t1",
        "/pool/currentTemp",
        "/notifications",
        "/signals/SRC.OutdoorTemp",
    ],
)
def test_plant_wide_branches_stay_on_the_gateway(
    system_info: SystemInfo, installation: Installation, path: str
) -> None:
    devices = tree(system_info, installation)
    assert devices.for_resource(path) == devices.hub


def test_a_branch_without_a_matching_id_falls_back_to_the_gateway(
    system_info: SystemInfo, installation: Installation
) -> None:
    """A circuit that was never discovered cannot have a device of its own."""
    devices = tree(system_info, installation)
    assert devices.for_candidate(candidate("/heatingCircuits/hc4/roomtemperature", "hc4")) == (
        devices.hub
    )


def test_a_gateway_with_bare_modules_still_describes_itself() -> None:
    """No module tells us anything: the hub keeps its own model, nothing more."""
    empty = SystemInfo(gateway_id=DEVICE_ID, modules=(SystemInfoModule(None, None, None, None),))
    devices = tree(empty, Installation(heating_circuits=("hc1",)))
    assert devices.hub["model"] == "K 40 RF"
    circuit = devices.for_resource("/heatingCircuits/hc1/roomtemperature", "hc1")
    assert circuit["model"] is None
    assert circuit["translation_key"] == "heating_circuit"


class TestSignalNames:
    """What the device says, the entity must not repeat -- and vice versa."""

    @pytest.mark.parametrize(
        ("signal", "expected"),
        [
            # Real ids. The device carries SRC/SC/VENTILATION and the circuit.
            ("VENTILATION.FrostProt.PreHeatPower", "Frost protection pre heat power"),
            ("VENTILATION.BasicFunction.VENT1.CurOpMode", "Basic function current operating mode"),
            ("SC.HC1.FlowTempSetp", "Flow temperature setpoint"),
            ("SC.DHW1.HolidayAutoTD", "Holiday auto thermal disinfection"),
            ("SRC.OutdoorTemp", "Outdoor temperature"),
            ("SRC.IntDHW.CylTemp", "Internal hot water cylinder temperature"),
            # A run of capitals splits too, or CHPumpSpeed reads as "chpump".
            ("SRC.CUHP.HP1.CHPumpSpeed", "CUHP heating pump speed"),
            ("SRC.CUHP.HP1.DHWValve", "CUHP hot water valve"),
            # Acronyms the API never spells out stay as the controller writes
            # them: a guess would read better and mean less.
            ("SC.HC1.FPD.Active", "FPD active"),
            ("SRC.CUHP.PC0ConnectedToLIN", "CUHP PC0 connected to LIN"),
            # On the gateway the leading segment has to stay, or this would
            # read like the system's own outdoor sensor.
            ("SC.DampOutdTemp", "System damped outdoor temperature"),
            ("GWEEBUS.Status", "EMS bus status"),
        ],
    )
    def test_a_signal_reads_as_a_name(
        self, system_info: SystemInfo, installation: Installation, signal: str, expected: str
    ) -> None:
        _, parts = tree(system_info, installation).signal_target(f"/signals/{signal}")
        assert signal_name(parts) == expected

    def test_a_mixer_module_still_says_it_is_the_module(self, system_info: SystemInfo) -> None:
        """On hc2's device the circuit drops out; the module must not.

        SC.HC2.FlowTempSetp is what the controller asks of the circuit,
        HC2MOD.FlowTemp what the mixer module measures. Two devices, one
        circuit -- so the name has to keep them apart.
        """
        devices = tree(system_info, Installation(heating_circuits=("hc1", "hc2")))
        _, parts = devices.signal_target("/signals/HC2MOD.FlowCtrl.MixerPosition")
        assert signal_name(parts) == "Module flow control mixer position"
        _, parts = devices.signal_target("/signals/HC2MOD.FlowTemp")
        assert signal_name(parts) == "Module flow temperature"

    def test_an_undiscovered_circuit_is_kept_in_the_name(
        self, system_info: SystemInfo, installation: Installation
    ) -> None:
        """No hc4 device, so the entity has to say which circuit it meant."""
        devices = tree(system_info, installation)
        device, parts = devices.signal_target("/signals/SC.HC4.FlowTempSetp")
        assert device == devices.hub
        assert signal_name(parts) == "System heating circuit 4 flow temperature setpoint"

    def test_a_cascade_keeps_the_head_on_the_gateway(self, system_info: SystemInfo) -> None:
        devices = tree(system_info, Installation(heat_sources=("hs1", "hs2")))
        _, parts = devices.signal_target("/signals/SRC.OutdoorTemp")
        assert signal_name(parts) == "Heat source outdoor temperature"
