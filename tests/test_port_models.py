from __future__ import annotations

import pytest

from engineering_automation.port.config import PortConfig, PortRegion
from engineering_automation.port.models import Entity


def test_region_base_urls() -> None:
    assert PortRegion.EU.base_url == "https://api.port.io"
    assert PortRegion.US.base_url == "https://api.us.port.io"


def test_config_uses_region_by_default() -> None:
    config = PortConfig("client", "secret", region=PortRegion.US)
    assert config.api_base_url == "https://api.us.port.io"


def test_config_normalizes_custom_base_url() -> None:
    config = PortConfig("client", "secret", base_url=" https://port.example.com/ ")
    assert config.api_base_url == "https://port.example.com"


@pytest.mark.parametrize(
    ("kwargs", "message"),
    [
        ({"client_id": ""}, "client_id"),
        ({"client_secret": " "}, "client_secret"),
        ({"timeout_seconds": 0}, "timeout_seconds"),
        ({"token_refresh_skew_seconds": -1}, "token_refresh_skew_seconds"),
        ({"base_url": "port.example.com"}, "base_url"),
        ({"base_url": "https://"}, "base_url"),
    ],
)
def test_config_rejects_invalid_values(kwargs: dict[str, object], message: str) -> None:
    values: dict[str, object] = {"client_id": "client", "client_secret": "secret"}
    values.update(kwargs)
    with pytest.raises(ValueError, match=message):
        PortConfig(**values)  # type: ignore[arg-type]


def test_entity_produces_port_payload() -> None:
    entity = Entity(
        identifier="payments",
        title="Payments",
        icon="Service",
        team=("platform", "payments"),
        properties={"tier": "critical"},
        relations={"system": "commerce"},
    )
    assert entity.to_payload() == {
        "identifier": "payments",
        "title": "Payments",
        "icon": "Service",
        "team": ["platform", "payments"],
        "properties": {"tier": "critical"},
        "relations": {"system": "commerce"},
    }


def test_entity_omits_absent_optional_fields() -> None:
    assert Entity("service-a").to_payload() == {
        "identifier": "service-a",
        "properties": {},
        "relations": {},
    }


def test_entity_requires_identifier() -> None:
    with pytest.raises(ValueError, match="identifier"):
        Entity(" ")
