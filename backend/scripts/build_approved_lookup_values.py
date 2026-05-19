from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import oracledb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.semantic_normalization.rules import normalize_text  # noqa: E402


def resolve_output_path(output_arg: str, overwrite: bool = False, project_root: Path = PROJECT_ROOT) -> Path:
    target_root = (project_root / "metadata" / "generated").resolve()
    target_root.mkdir(parents=True, exist_ok=True)
    output = Path(output_arg)
    output = (project_root / output).resolve() if not output.is_absolute() else output.resolve()
    if target_root != output and target_root not in output.parents:
        raise ValueError("--output debe estar dentro de metadata/generated/")
    if output.exists() and not overwrite:
        raise FileExistsError("El archivo de salida ya existe. Use --overwrite")
    return output


def _build_dsn(settings: Any) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(settings.db_host, settings.db_port, service_name=settings.db_service_name)


def _extract_fixed_filter_value(fixed_filter: str) -> str:
    fixed = str(fixed_filter or "")
    marker = "="
    if marker not in fixed:
        return ""
    _, right = fixed.split(marker, 1)
    return right.strip().strip("'").strip('"')


def _normalize_synonyms(description: str) -> list[str]:
    collapsed = " ".join((description or "").strip().lower().split())
    normalized = normalize_text(description)
    return [item for item in dict.fromkeys([normalized, collapsed]) if item]


def load_approved_multitabla_mappings(metadata_path: Path) -> list[dict[str, str]]:
    target = metadata_path / "curated" / "business_overrides.yml"
    if not target.exists():
        return []
    payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
    mappings = payload.get("approved_parametric_mappings", []) or []
    selected: list[dict[str, str]] = []
    for item in mappings:
        if str(item.get("lookup_table", "")).upper() != "SAC.MULTITABLA":
            continue
        fixed_filter_value = _extract_fixed_filter_value(str(item.get("fixed_filter", "")))
        if not fixed_filter_value:
            continue
        selected.append(
            {
                "source_table": str(item.get("source_table", "")).upper(),
                "source_column": str(item.get("source_column", "")).upper(),
                "lookup_table": "SAC.MULTITABLA",
                "lookup_key": str(item.get("lookup_key", "")).upper(),
                "lookup_description": str(item.get("lookup_description", "DESCRIPCION")).upper(),
                "fixed_filter_value": fixed_filter_value,
            }
        )
    return selected


def fetch_lookup_rows(connection: Any, fixed_filter_value: str) -> list[dict[str, Any]]:
    cursor = connection.cursor()
    try:
        cursor.execute(
            """
            SELECT TABLA, CODIGO_CAR, CODIGO_NUM, DESCRIPCION
            FROM SAC.MULTITABLA
            WHERE TABLA = :fixed_filter_value
              AND DESCRIPCION IS NOT NULL
            """,
            {"fixed_filter_value": fixed_filter_value},
        )
        rows: list[dict[str, Any]] = []
        for tabla, codigo_car, codigo_num, descripcion in cursor.fetchall():
            rows.append(
                {
                    "TABLA": tabla,
                    "CODIGO_CAR": codigo_car,
                    "CODIGO_NUM": codigo_num,
                    "DESCRIPCION": descripcion,
                }
            )
        return rows
    finally:
        cursor.close()


def build_payload(
    mappings: list[dict[str, str]],
    rows_by_filter: dict[str, list[dict[str, Any]]],
) -> dict[str, Any]:
    warnings: list[str] = []
    approved_lookup_values: list[dict[str, Any]] = []
    global_description_index: dict[str, set[str]] = {}

    for mapping in mappings:
        fixed_filter_value = mapping["fixed_filter_value"]
        rows = rows_by_filter.get(fixed_filter_value, [])
        if not rows:
            warnings.append(f"fixed_filter_without_rows:{mapping['source_table']}.{mapping['source_column']}:{fixed_filter_value}")
            approved_lookup_values.append(
                {
                    **mapping,
                    "values": [],
                }
            )
            continue

        values: list[dict[str, Any]] = []
        normalized_seen: dict[str, str] = {}
        for row in rows:
            code_field = mapping["lookup_key"]
            code_value = row.get(code_field)
            description = str(row.get("DESCRIPCION") or "").strip()
            if code_value in (None, "") or not description:
                continue
            code = str(code_value).strip()
            normalized_description = normalize_text(description)
            if normalized_description in normalized_seen and normalized_seen[normalized_description] != code:
                warnings.append(
                    f"duplicate_normalized_description:{mapping['source_table']}.{mapping['source_column']}:{fixed_filter_value}:{normalized_description}"
                )
            normalized_seen[normalized_description] = code
            synonyms = _normalize_synonyms(description)
            values.append(
                {
                    "code": code,
                    "description": description,
                    "normalized_description": normalized_description,
                    "synonyms": synonyms,
                }
            )
            key = normalized_description
            global_description_index.setdefault(key, set()).add(
                f"{mapping['source_table']}.{mapping['source_column']}:{fixed_filter_value}"
            )

        approved_lookup_values.append({**mapping, "values": values})

    for normalized_description, owners in global_description_index.items():
        if len(owners) > 1:
            warnings.append(
                f"cross_mapping_duplicate_description:{normalized_description}:{'|'.join(sorted(owners))}"
            )

    return {
        "approved_lookup_values": approved_lookup_values,
        "warnings": warnings,
    }


def run(*, output: str, overwrite: bool = False, project_root: Path = PROJECT_ROOT) -> int:
    settings = get_settings()
    metadata_path = (project_root / "metadata").resolve()
    output_path = resolve_output_path(output, overwrite=overwrite, project_root=project_root)
    mappings = load_approved_multitabla_mappings(metadata_path)

    connection = None
    try:
        connection = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=_build_dsn(settings),
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        rows_by_filter = {
            mapping["fixed_filter_value"]: fetch_lookup_rows(connection, mapping["fixed_filter_value"])
            for mapping in mappings
        }
        payload = build_payload(mappings, rows_by_filter)
        output_path.write_text(
            yaml.safe_dump(payload, sort_keys=False, allow_unicode=False),
            encoding="utf-8",
        )
        print("Estado: OK")
        print(f"mappings: {len(mappings)}")
        print(f"warnings: {len(payload.get('warnings', []))}")
        print(f"output: {output_path}")
        return 0
    except Exception as exc:
        msg = str(exc)
        if settings.db_password:
            msg = msg.replace(settings.db_password, "***")
        print("Estado: ERROR")
        print(msg)
        return 1
    finally:
        if connection is not None:
            connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Construye un catalogo generated de valores aprobados desde SAC.MULTITABLA")
    parser.add_argument(
        "--output",
        default="metadata/generated/approved_lookup_values.yml",
        help="Archivo YAML generado dentro de metadata/generated/",
    )
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(output=args.output, overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
