from __future__ import annotations

import pytest

from engineering_automation.bootstrap.api import ApiSettings
from engineering_automation.port.config import PortRegion


def environment(**overrides: str) -> dict[str, str]:
    values = {
        "AUTOMATION_API_KEY": "service-secret",
        "PORT_CLIENT_ID": "port-client",
        "PORT_CLIENT_SECRET": "port-secret",
        "PORT_AUTOMATION_BLUEPRINT": "engineeringAutomation",
        "N8N_BASE_URL": "https://n8n.example.com",
        "N8N_API_KEY": "n8n-secret",
    }
    values.update(overrides)
    return values


def test_settings_load_required_values_and_defaults() -> None:
    settings = ApiSettings.from_mapping(environment())

    assert settings.port_region is PortRegion.EU
    assert settings.max_concurrency == 5
    assert settings.port_base_url is None
    assert "service-secret" not in repr(settings)
    assert "port-secret" not in repr(settings)
    assert "n8n-secret" not in repr(settings)


def test_settings_load_optional_region_endpoint_and_concurrency() -> None:
    settings = ApiSettings.from_mapping(
        environment(
            PORT_REGION="US",
            PORT_BASE_URL="https://port.example.com",
            AUTOMATION_MAX_CONCURRENCY="12",
        )
    )

    assert settings.port_region is PortRegion.US
    assert settings.port_base_url == "https://port.example.com"
    assert settings.max_concurrency == 12


@pytest.mark.parametrize(
    "name",
    [
        "AUTOMATION_API_KEY",
        "PORT_CLIENT_ID",
        "PORT_CLIENT_SECRET",
        "PORT_AUTOMATION_BLUEPRINT",
        "N8N_BASE_URL",
        "N8N_API_KEY",
    ],
)
def test_settings_require_all_credentials_and_endpoints(name: str) -> None:
    values = environment()
    values.pop(name)

    with pytest.raises(ValueError, match=f"{name} is required"):
        ApiSettings.from_mapping(values)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"PORT_REGION": "asia"}, "PORT_REGION must be 'eu' or 'us'"),
        (
            {"AUTOMATION_MAX_CONCURRENCY": "many"},
            "AUTOMATION_MAX_CONCURRENCY must be an integer",
        ),
        (
            {"AUTOMATION_MAX_CONCURRENCY": "0"},
            "AUTOMATION_MAX_CONCURRENCY must be at least 1",
        ),
    ],
)
def test_settings_reject_invalid_operational_values(
    overrides: dict[str, str],
    message: str,
) -> None:
    with pytest.raises(ValueError, match=message):
        ApiSettings.from_mapping(environment(**overrides))
