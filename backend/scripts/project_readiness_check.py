from __future__ import annotations

import argparse
import json
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from app.core.config import get_settings

PROJECT_ROOT = Path(__file__).resolve().parents[1]
CRITICAL_SCRIPTS = [
    "check_oracle_connection.py",
    "inspect_oracle_schema.py",
    "review_oracle_catalog.py",
    "promote_oracle_catalog.py",
    "oracle_catalog_smoke_test.py",
    "evaluate_text_to_sql.py",
    "bootstrap_real_catalog.py",
]
PLACEHOLDER_VALUES = {
    "",
    "CHANGE_ME",
    "YOUR_USER",
    "YOUR_PASSWORD",
    "USER",
    "PASSWORD",
    "READONLY_USER",
    "READONLY",
    "TEST",
    "DEMO",
    "EXAMPLE",
}


@dataclass
class CheckItem:
    name: str
    status: str
    detail: str


@dataclass
class ReadinessReport:
    ok: bool
    summary: dict[str, int]
    items: list[CheckItem]


def resolve_output_path(output_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    outputs_root = (project_root / "outputs").resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_arg)
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()
    else:
        output_path = output_path.resolve()
    if outputs_root != output_path and outputs_root not in output_path.parents:
        raise ValueError("--json-output debe estar dentro de outputs/")
    return output_path


def _is_placeholder(value: str) -> bool:
    normalized = value.strip().upper()
    return normalized in PLACEHOLDER_VALUES or "<" in normalized or ">" in normalized


def _add_item(items: list[CheckItem], name: str, ok: bool, detail_ok: str, detail_error: str) -> None:
    items.append(CheckItem(name=name, status="OK" if ok else "ERROR", detail=detail_ok if ok else detail_error))


def evaluate_project_readiness(project_root: Path = PROJECT_ROOT, settings: Any | None = None) -> ReadinessReport:
    settings = settings or get_settings()
    items: list[CheckItem] = []

    env_file = project_root / ".env"
    _add_item(
        items,
        ".env exists",
        env_file.exists(),
        "Found .env",
        "Missing .env file",
    )

    _add_item(
        items,
        "DB_DIALECT=oracle",
        str(settings.db_dialect).lower().endswith("oracle") or str(settings.db_dialect).lower() == "oracle",
        "Oracle dialect configured",
        f"Unexpected DB_DIALECT={settings.db_dialect}",
    )

    _add_item(items, "DB_HOST configured", bool(str(settings.db_host).strip()), "DB_HOST configured", "DB_HOST missing")
    _add_item(items, "DB_PORT configured", int(settings.db_port) > 0, "DB_PORT configured", "DB_PORT invalid")

    has_service_or_sid = bool(str(settings.db_service_name).strip()) or bool(str(settings.db_sid).strip())
    _add_item(
        items,
        "DB_SERVICE_NAME or DB_SID configured",
        has_service_or_sid,
        "Service/SID configured",
        "Missing DB_SERVICE_NAME and DB_SID",
    )

    user_ok = bool(str(settings.db_user).strip()) and not _is_placeholder(str(settings.db_user))
    _add_item(items, "DB_USER valid", user_ok, "DB_USER looks valid", "DB_USER missing or placeholder")

    password_ok = bool(str(settings.db_password).strip()) and not _is_placeholder(str(settings.db_password))
    _add_item(items, "DB_PASSWORD valid", password_ok, "DB_PASSWORD looks valid", "DB_PASSWORD missing or placeholder")

    _add_item(
        items,
        "CATALOG_REQUIRE_APPROVAL=true",
        bool(settings.catalog_require_approval),
        "Approval gate enabled",
        "CATALOG_REQUIRE_APPROVAL should be true",
    )

    _add_item(
        items,
        "QUERY_DRY_RUN_DEFAULT=true",
        bool(settings.query_dry_run_default),
        "Dry-run default enabled",
        "QUERY_DRY_RUN_DEFAULT should be true",
    )

    if bool(settings.query_allow_execution):
        items.append(
            CheckItem(
                name="QUERY_ALLOW_EXECUTION=false",
                status="WARNING",
                detail="Execution enabled; recommended false before loading real tables",
            )
        )
    else:
        items.append(CheckItem(name="QUERY_ALLOW_EXECUTION=false", status="OK", detail="Execution blocked by default"))

    _add_item(
        items,
        "metadata/generated exists",
        (project_root / "metadata" / "generated").exists(),
        "metadata/generated present",
        "metadata/generated missing",
    )
    _add_item(
        items,
        "metadata/approvals exists",
        (project_root / "metadata" / "approvals").exists(),
        "metadata/approvals present",
        "metadata/approvals missing",
    )
    _add_item(
        items,
        "metadata/evaluation/questions.yml exists",
        (project_root / "metadata" / "evaluation" / "questions.yml").exists(),
        "questions.yml present",
        "metadata/evaluation/questions.yml missing",
    )

    scripts_root = project_root / "scripts"
    for script_name in CRITICAL_SCRIPTS:
        _add_item(
            items,
            f"script exists: {script_name}",
            (scripts_root / script_name).exists(),
            f"{script_name} present",
            f"{script_name} missing",
        )

    summary = {
        "ok": sum(1 for item in items if item.status == "OK"),
        "warning": sum(1 for item in items if item.status == "WARNING"),
        "error": sum(1 for item in items if item.status == "ERROR"),
    }
    return ReadinessReport(ok=summary["error"] == 0, summary=summary, items=items)


def print_report(report: ReadinessReport) -> None:
    for item in report.items:
        print(f"[{item.status}] {item.name}: {item.detail}")
    print(f"Resumen: OK={report.summary['ok']} WARNING={report.summary['warning']} ERROR={report.summary['error']}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Diagnostico de readiness del proyecto para carga real Oracle")
    parser.add_argument("--json-output", required=False, help="Salida JSON dentro de outputs/")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    report = evaluate_project_readiness(project_root=PROJECT_ROOT)
    print_report(report)

    if args.json_output:
        output_path = resolve_output_path(args.json_output)
        payload = {
            "ok": report.ok,
            "summary": report.summary,
            "items": [asdict(item) for item in report.items],
        }
        output_path.write_text(json.dumps(payload, indent=2, ensure_ascii=True), encoding="utf-8")
        print(f"json_output: {output_path}")

    return 0 if report.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
