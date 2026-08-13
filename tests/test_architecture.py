from __future__ import annotations

import ast
from pathlib import Path

PACKAGE_ROOT = Path(__file__).parents[1] / "src" / "engineering_automation"


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


def assert_layer_avoids(layer: str, forbidden: tuple[str, ...]) -> None:
    violations: list[str] = []
    for path in sorted((PACKAGE_ROOT / layer).rglob("*.py")):
        for module in imported_modules(path):
            if module.startswith(forbidden):
                violations.append(f"{path.relative_to(PACKAGE_ROOT)} imports {module}")
    assert not violations, "Forbidden inward dependencies:\n" + "\n".join(violations)


def test_domain_has_no_outward_dependencies() -> None:
    assert_layer_avoids(
        "domain",
        (
            "engineering_automation.application",
            "engineering_automation.bootstrap",
            "engineering_automation.infrastructure",
            "engineering_automation.interfaces",
            "engineering_automation.n8n",
            "engineering_automation.notifications",
            "engineering_automation.port",
            "engineering_automation.webhooks",
        ),
    )


def test_application_does_not_depend_on_outer_layers() -> None:
    assert_layer_avoids(
        "application",
        (
            "engineering_automation.bootstrap",
            "engineering_automation.infrastructure",
            "engineering_automation.interfaces",
            "engineering_automation.n8n",
            "engineering_automation.notifications",
            "engineering_automation.port",
            "engineering_automation.webhooks",
        ),
    )


def test_interfaces_do_not_select_infrastructure() -> None:
    assert_layer_avoids(
        "interfaces",
        (
            "engineering_automation.bootstrap",
            "engineering_automation.infrastructure",
            "engineering_automation.n8n",
            "engineering_automation.port",
            "engineering_automation.webhooks",
        ),
    )


def test_n8n_handler_depends_on_webhook_port_not_concrete_dispatcher() -> None:
    modules = imported_modules(PACKAGE_ROOT / "n8n" / "handler.py")
    assert "engineering_automation.application.ports.webhooks" in modules
    assert "engineering_automation.webhooks.delivery" not in modules
