"""Translation completeness."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from custom_components.nibe_internal_bus.binary_sensor import BINARY_SENSORS
from custom_components.nibe_internal_bus.sensor import SENSORS

COMPONENT = Path(__file__).parents[1] / "custom_components" / "nibe_internal_bus"
STRINGS = COMPONENT / "strings.json"
TRANSLATIONS = COMPONENT / "translations"


def load(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))


def key_paths(node, prefix: str = "") -> set[str]:
    if not isinstance(node, dict):
        return {prefix}
    return {
        path
        for key, value in node.items()
        for path in key_paths(value, f"{prefix}.{key}" if prefix else key)
    }


def test_english_translation_matches_strings() -> None:
    assert load(STRINGS) == load(TRANSLATIONS / "en.json")


@pytest.mark.parametrize("language", ["fi"])
def test_translation_has_the_same_keys_as_english(language: str) -> None:
    english = key_paths(load(TRANSLATIONS / "en.json"))
    other = key_paths(load(TRANSLATIONS / f"{language}.json"))

    assert english - other == set(), f"{language} is missing keys"
    assert other - english == set(), f"{language} has unknown keys"


@pytest.mark.parametrize("language", ["en", "fi"])
def test_every_entity_has_a_name(language: str) -> None:
    entity = load(TRANSLATIONS / f"{language}.json")["entity"]

    for description in SENSORS:
        assert entity["sensor"][description.key]["name"]
    for description in BINARY_SENSORS:
        assert entity["binary_sensor"][description.key]["name"]


@pytest.mark.parametrize("language", ["en", "fi"])
def test_enum_sensors_translate_every_option(language: str) -> None:
    entity = load(TRANSLATIONS / f"{language}.json")["entity"]["sensor"]

    for description in SENSORS:
        if not description.options:
            continue
        states = entity[description.key]["state"]
        assert set(states) == set(description.options), description.key
