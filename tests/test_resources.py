"""Catalogue expansion: the rule that makes other installations work."""

from __future__ import annotations

import json
from pathlib import Path

from pyk40rf import Installation
from pyk40rf.const import PROBE_PATHS

from custom_components.bosch_k40rf.binary_resources import BINARY_RESOURCES, BY_TEMPLATE
from custom_components.bosch_k40rf.catalog import BY_PATH, CATALOG
from custom_components.bosch_k40rf.naming import component_key, english_name, translation_key
from custom_components.bosch_k40rf.resources import ENTITY_TYPES, candidates_for


def test_the_catalogue_covers_the_whole_spec() -> None:
    assert len(CATALOG) > 190
    assert len(BY_PATH) == len(CATALOG)
    assert any(spec.live_confirmed for spec in CATALOG)


def test_nothing_is_expanded_for_an_installation_with_no_circuits() -> None:
    plain = candidates_for(Installation())
    assert plain
    # Only the system-wide resources survive.
    assert all(not candidate.spec.is_templated for candidate in plain)


def test_a_single_circuit_house_gets_one_of_each() -> None:
    candidates = candidates_for(Installation(heat_sources=("hs1",), heating_circuits=("hc1",)))
    paths = {candidate.path for candidate in candidates}

    assert "/heatSources/hs1/numberOfStarts" in paths
    assert "/heatSources/hs2/numberOfStarts" not in paths
    assert "/heatingCircuits/hc2/currentRoomSetpoint" not in paths


def test_a_cascade_gets_every_heat_source() -> None:
    """The test device has one heat source; a cascade has up to six."""
    candidates = candidates_for(Installation(heat_sources=("hs1", "hs2", "hs3")))
    starts = {c.path for c in candidates if c.path.endswith("/numberOfStarts")}

    assert "/heatSources/hs1/numberOfStarts" in starts
    assert "/heatSources/hs3/numberOfStarts" in starts
    # The system-wide resource of the same name is still there and distinct.
    assert "/heatSources/numberOfStarts" in starts


def test_solar_appears_only_where_it_exists() -> None:
    without = {c.path for c in candidates_for(Installation())}
    with_solar = {c.path for c in candidates_for(Installation(solar_circuits=("sc1",)))}

    assert not any(path.startswith("/solarCircuits/") for path in without)
    assert "/solarCircuits/sc1/collectorTemperature" in with_solar


def test_structural_resources_never_become_entities() -> None:
    candidates = candidates_for(Installation(heat_sources=("hs1",)))
    assert all(candidate.value_type in ENTITY_TYPES for candidate in candidates)
    assert "/notifications" not in {c.path for c in candidates}


def test_history_is_not_polled() -> None:
    """Recordings are read on demand; polling 28 of them would be absurd."""
    assert not any(spec.path.startswith("/recordings/") for spec in CATALOG)


def test_the_circuit_id_is_kept_for_naming() -> None:
    candidates = candidates_for(Installation(heating_circuits=("hc1", "hc2")))
    hc2 = next(c for c in candidates if c.path.startswith("/heatingCircuits/hc2/"))
    assert hc2.circuit_id == "hc2"


class TestNaming:
    """Names and keys are user-visible and permanent, so they are pinned."""

    def test_keys_are_unique_across_the_catalogue(self) -> None:
        keys = [translation_key(spec.path) for spec in CATALOG]
        assert len(set(keys)) == len(keys)

    def test_a_per_circuit_key_differs_from_the_system_wide_one(self) -> None:
        assert translation_key("/heatSources/numberOfStarts") != translation_key(
            "/heatSources/{heatSourceId}/numberOfStarts"
        )

    def test_abbreviations_are_expanded(self) -> None:
        assert english_name("/dhwCircuits/{dhwCircuitId}/actualTemp") == "Actual temperature"

    def test_a_branch_with_a_device_is_not_repeated_in_the_name(self) -> None:
        """The entity sits on "Hot water"; saying it twice helps nobody."""
        assert english_name("/heatingCircuits/{heatingCircuitId}/roomtemperature") == (
            "Room temperature"
        )
        assert english_name("/ventilation/{ventilationZoneId}/ventilationMode") == "Mode"

    def test_a_branch_without_a_device_keeps_its_label(self) -> None:
        """Gateway and system share the hub, and would otherwise collide."""
        assert english_name("/gateway/update/status") == "Gateway update status"
        assert english_name("/system/update/status") == "System update status"

    def test_a_repeated_branch_word_is_dropped_only_when_whole(self) -> None:
        # "heatCarrierPump" must keep its "heat".
        assert "heat carrier" in english_name(
            "/heatSources/{heatSourceId}/refrigerant/heatCarrierPumpSpeed"
        )

    def test_structural_segments_are_not_names(self) -> None:
        assert english_name("/ventilation/{ventilationZoneId}/sensors/supplyTemp") == (
            "Supply temperature"
        )

    def test_names_are_unique_per_device(self) -> None:
        """Two entities on one device page must not read the same.

        The branch decides the device, so grouping by it is the same grouping
        the device registry ends up with -- except for a cascade, where the
        entities spread over more devices, never fewer.
        """
        by_branch: dict[str, list[str]] = {}
        for spec in CATALOG:
            if spec.value_type not in ENTITY_TYPES:
                continue
            branch = spec.path.strip("/").split("/")[0]
            by_branch.setdefault(branch, []).append(english_name(spec.path))
        for branch, names in by_branch.items():
            duplicates = {name for name in names if names.count(name) > 1}
            assert not duplicates, f"{branch}: {duplicates}"

    def test_every_entity_resource_has_a_name(self) -> None:
        for spec in CATALOG:
            if spec.value_type not in ENTITY_TYPES:
                continue
            assert english_name(spec.path).strip()
            assert translation_key(spec.path).strip()


class TestBinaryResources:
    """Every binary sensor must name a resource the API actually declares."""

    def test_every_declared_path_exists_in_the_catalogue(self) -> None:
        for resource in BINARY_RESOURCES:
            assert resource.path in BY_PATH, f"{resource.path} is not in the API spec"

    def test_every_on_value_is_one_the_resource_can_report(self) -> None:
        """A polarity typed from memory would silently never turn on."""
        for resource in BINARY_RESOURCES:
            options = {option.lower() for option in BY_PATH[resource.path].options}
            if not options:
                continue
            assert resource.on_values <= options, (
                f"{resource.path}: {resource.on_values - options} cannot occur"
            )

    def test_a_binary_resource_is_never_also_a_sensor(self) -> None:
        installation = Installation(
            heat_sources=("hs1",), heating_circuits=("hc1",), dhw_circuits=("dhw1",)
        )
        sensors = [
            candidate
            for candidate in candidates_for(installation)
            if candidate.spec.path not in BY_TEMPLATE
        ]
        assert len(sensors) < len(candidates_for(installation))


class TestTranslations:
    """Every entity the platforms can create must have a name to show."""

    def test_every_catalogue_entity_has_a_string(self) -> None:
        strings = json.loads(
            (
                Path(__file__).parent.parent / "custom_components/bosch_k40rf/strings.json"
            ).read_text()
        )
        declared = strings["entity"]["sensor"]

        for spec in CATALOG:
            if spec.value_type not in ENTITY_TYPES:
                continue
            assert translation_key(spec.path) in declared, spec.path
            for component in spec.components:
                key = f"{translation_key(spec.path)}_{component_key(component)}"
                assert key in declared, key

    def test_the_english_translation_matches_strings_json(self) -> None:
        """A custom install reads translations/en.json, Core reads strings.json."""
        component = Path(__file__).parent.parent / "custom_components/bosch_k40rf"
        assert json.loads((component / "strings.json").read_text()) == json.loads(
            (component / "translations/en.json").read_text()
        )

    def test_the_german_translation_covers_the_whole_config_flow(self) -> None:
        component = Path(__file__).parent.parent / "custom_components/bosch_k40rf"
        english = json.loads((component / "strings.json").read_text())
        german = json.loads((component / "translations/de.json").read_text())

        assert set(german["config"]["step"]) == set(english["config"]["step"])
        assert set(german["config"]["error"]) == set(english["config"]["error"])
        assert set(german["config"]["abort"]) == set(english["config"]["abort"])
        assert set(german["exceptions"]) == set(english["exceptions"])


class TestProbePaths:
    """The library probes for circuits; those paths must be real.

    An invented probe path is not harmless: the gateway answers 403 rather
    than 404 for paths outside the published specification, and a 403 used to
    be read as a rejected token. One made-up path took a live installation
    down at setup.
    """

    #: Which installation id fills each family's placeholder.
    FAMILY_PLACEHOLDERS = {
        "heat_sources": "heatSourceId",
        "heating_circuits": "heatingCircuitId",
        "dhw_circuits": "dhwCircuitId",
        "solar_circuits": "solarCircuitId",
        "ventilation_zones": "ventilationZoneId",
        "zones": "zoneId",
        "devices": "deviceId",
    }

    def test_every_probe_path_exists_in_the_specification(self) -> None:
        for family, templates in PROBE_PATHS.items():
            placeholder = self.FAMILY_PLACEHOLDERS[family]
            for template in templates:
                path = template.replace("{id}", "{" + placeholder + "}")
                assert path in BY_PATH, f"{path} is not in the API specification"

    def test_every_family_is_covered(self) -> None:
        assert set(PROBE_PATHS) == set(self.FAMILY_PLACEHOLDERS)

    def test_each_family_has_more_than_one_probe_path(self) -> None:
        """Installations differ in kind: a gas boiler has no compressor."""
        for family, templates in PROBE_PATHS.items():
            assert len(templates) >= 2, family
