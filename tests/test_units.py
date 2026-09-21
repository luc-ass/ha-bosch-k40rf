"""Unit, device class and state class mapping."""

from __future__ import annotations

import pytest

from custom_components.bosch_k40rf.units import mapping_for
from homeassistant.components.sensor import SensorDeviceClass, SensorStateClass
from homeassistant.const import PERCENTAGE, UnitOfEnergy, UnitOfTemperature


@pytest.mark.parametrize(
    ("unit", "path", "expected_unit", "expected_class"),
    [
        ("C", "/x", UnitOfTemperature.CELSIUS, SensorDeviceClass.TEMPERATURE),
        ("kWh", "/x", UnitOfEnergy.KILO_WATT_HOUR, SensorDeviceClass.ENERGY),
        ("%", "/heatingCircuits/hc1/actualHumidity", PERCENTAGE, SensorDeviceClass.HUMIDITY),
        ("%", "/devices/device1/battery", PERCENTAGE, SensorDeviceClass.BATTERY),
    ],
)
def test_known_units_get_their_device_class(
    unit: str, path: str, expected_unit: str, expected_class: SensorDeviceClass
) -> None:
    mapping = mapping_for(unit, path)
    assert mapping.unit == expected_unit
    assert mapping.device_class is expected_class


def test_a_plain_percentage_gets_no_device_class() -> None:
    """A modulation in percent is not a humidity reading."""
    mapping = mapping_for("%", "/heatSources/actualModulation")
    assert mapping.unit == PERCENTAGE
    assert mapping.device_class is None


def test_energy_counters_are_totals() -> None:
    assert mapping_for("kWh", "/x").state_class is SensorStateClass.TOTAL_INCREASING


def test_a_run_time_is_a_total_not_a_duration_reading() -> None:
    mapping = mapping_for("mins", "/ventilation/zone1/applianceRunTime")
    assert mapping.device_class is SensorDeviceClass.DURATION
    assert mapping.state_class is SensorStateClass.TOTAL_INCREASING


def test_a_remaining_time_stays_a_measurement() -> None:
    assert (
        mapping_for("mins", "/dhwCircuits/dhw1/chargeRemainingTime").state_class
        is SensorStateClass.MEASUREMENT
    )


def test_a_unitless_counter_is_still_a_total() -> None:
    mapping = mapping_for(None, "/heatSources/numberOfStarts")
    assert mapping.unit is None
    assert mapping.state_class is SensorStateClass.TOTAL_INCREASING


def test_a_unitless_value_gets_no_state_class() -> None:
    assert mapping_for(None, "/gateway/versionFirmware").state_class is None


def test_an_unknown_unit_is_passed_through_without_a_class() -> None:
    """Guessing a device class for an unknown unit would break conversion."""
    mapping = mapping_for("furlongs", "/x")
    assert mapping.unit == "furlongs"
    assert mapping.device_class is None
    assert mapping.state_class is SensorStateClass.MEASUREMENT


class TestMultiCounterResources:
    """Not every emonValue is energy."""

    def test_start_counts_are_not_kilowatt_hours(self) -> None:
        """NumberOfStarts arrives in the same shape as an energy balance."""
        mapping = mapping_for(None, "/heatSources/hs1/numberOfStarts")
        assert mapping.unit is None
        assert mapping.device_class is None
        assert mapping.state_class is SensorStateClass.TOTAL_INCREASING

    def test_working_times_are_durations(self) -> None:
        mapping = mapping_for("s", "/heatSources/hs1/workingTime")
        assert mapping.device_class is SensorDeviceClass.DURATION
        assert mapping.state_class is SensorStateClass.TOTAL_INCREASING

    def test_consumption_counters_are_energy(self) -> None:
        mapping = mapping_for("kWh", "/heatSources/emon/totalConsumption")
        assert mapping.device_class is SensorDeviceClass.ENERGY


class TestTheControllersOwnCounters:
    """The signal branch spells its counters differently from the catalogue.

    Its ids are dotted, and the controller marks its own lifetime counters
    with a ``Stats`` segment. Read as momentary values they produced an
    hourly mean of a number that only ever goes up.
    """

    @pytest.mark.parametrize(
        ("unit", "path"),
        [
            ("s", "/signals/SRC.CUHP.HP1.Stats.CompressorCH"),
            ("s", "/signals/SRC.CUHP.HP1.Stats.CompressorDHW"),
            ("s", "/signals/SRC.CUHP.Stats.ControlUnit"),
        ],
    )
    def test_a_stats_counter_is_a_total(self, unit: str, path: str) -> None:
        mapping = mapping_for(unit, path)
        assert mapping.device_class is SensorDeviceClass.DURATION
        assert mapping.state_class is SensorStateClass.TOTAL_INCREASING

    def test_a_start_count_without_a_unit_is_a_total(self) -> None:
        """The gateway reports this one as a bare number."""
        mapping = mapping_for(None, "/signals/SRC.CUHP.HP1.Stats.CompStartsCooling")
        assert mapping.unit is None
        assert mapping.state_class is SensorStateClass.TOTAL_INCREASING

    @pytest.mark.parametrize(
        "path",
        [
            "/signals/SRC.CUHP.HP1.Timer.CompressorRestart",
            "/signals/SRC.CUHP.HP1.Timer.TDWarmKeeping",
            "/signals/SC.SeasonOpt.TimerStopHeatingSeason",
        ],
    )
    def test_a_timer_counts_down_and_stays_a_measurement(self, path: str) -> None:
        assert mapping_for("s", path).state_class is SensorStateClass.MEASUREMENT


class TestADateIsNotADuration:
    """``SC.InstallationDate.*`` is one date in three readings.

    Day 1, month 10, year 25: the first of October 2025. Charted as durations
    they claimed the plant had run for a day, and the mean of "month" over an
    hour means nothing at all.
    """

    @pytest.mark.parametrize(
        ("unit", "path"),
        [
            ("day", "/signals/SC.InstallationDate.Day"),
            ("month", "/signals/SC.InstallationDate.Month"),
            ("year", "/signals/SC.InstallationDate.Year"),
        ],
    )
    def test_it_carries_no_class_and_no_unit(self, unit: str, path: str) -> None:
        mapping = mapping_for(unit, path)
        assert mapping.unit is None
        assert mapping.device_class is None
        assert mapping.state_class is None

    def test_a_real_duration_still_is_one(self) -> None:
        """Spans of time arrive in seconds or minutes, never in days."""
        assert mapping_for("s", "/signals/SRC.CUHP.HP1.Timer.CompressorRestart").device_class is (
            SensorDeviceClass.DURATION
        )
