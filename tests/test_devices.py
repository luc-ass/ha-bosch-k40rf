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
