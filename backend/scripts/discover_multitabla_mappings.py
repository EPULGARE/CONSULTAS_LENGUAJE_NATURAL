from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path
from typing import Any

import oracledb
import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from scripts.inspect_oracle_schema import parse_table_names, validate_schema_name  # noqa: E402

HINT_PATTERNS = (
    re.compile(r"\[([A-Z0-9_]+)\]"),
    re.compile(r"\bTABLA\s+([A-Z0-9_]+)\b"),
    re.compile(r"\bPARAMETRIZAD[OA]\s+EN\s+([A-Z0-9_]+)\b"),
)
SAFE_HINT_PATTERN = re.compile(r"^[A-Z0-9_]+$")


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


def _build_in_clause(values: list[str], prefix: str) -> tuple[str, dict[str, str]]:
    binds: dict[str, str] = {}
    placeholders: list[str] = []
    for i, value in enumerate(values):
        key = f"{prefix}{i}"
        placeholders.append(f":{key}")
        binds[key] = value
    return ", ".join(placeholders), binds


def extract_multitabla_hint(comment: str) -> str | None:
    text = (comment or "").upper()
    for pattern in HINT_PATTERNS:
        match = pattern.search(text)
        if match:
            hint = match.group(1).strip().upper()
            return hint if SAFE_HINT_PATTERN.fullmatch(hint) else None
    return None


def load_oracle_comments(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {"tables": {}}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {"tables": {}}


def collect_comment_hints(comments_payload: dict[str, Any], schema: str, tables: list[str]) -> list[dict[str, str]]:
    selected = {f"{schema}.{table}" for table in tables}
    rows: list[dict[str, str]] = []
    for full_name, table_info in (comments_payload.get("tables") or {}).items():
        if str(full_name).upper() not in selected:
            continue
        for column_name, column_info in ((table_info or {}).get("columns") or {}).items():
            comment = str((column_info or {}).get("comment") or "")
            hint = extract_multitabla_hint(comment)
            if hint:
                rows.append(
                    {
                        "source_table": str(full_name).upper(),
                        "source_column": str(column_name).upper(),
                        "hint": hint,
                        "comment_hint": comment.strip(),
                    }
                )
    return rows


def fetch_multitabla_reference(connection: Any, schema: str) -> tuple[set[str], dict[str, dict[str, int]]]:
    cursor = connection.cursor()
    try:
        cursor.execute(f"SELECT DISTINCT TABLA FROM {schema}.MULTITABLA WHERE TABLA IS NOT NULL")
        available = {str(row[0]).upper() for row in cursor.fetchall() if row and row[0]}
        if not available:
            return set(), {}

        in_clause, binds = _build_in_clause(sorted(available), "t")
        cursor.execute(
            f"""
            SELECT TABLA, COUNT(CODIGO_NUM) AS CNT_NUM, COUNT(CODIGO_CAR) AS CNT_CAR
            FROM {schema}.MULTITABLA
            WHERE TABLA IN ({in_clause})
            GROUP BY TABLA
            """,
            binds,
        )
        stats: dict[str, dict[str, int]] = {}
        for row in cursor.fetchall():
            tabla = str(row[0]).upper()
            stats[tabla] = {
                "cnt_num": int(row[1] or 0),
                "cnt_car": int(row[2] or 0),
            }
        return available, stats
    finally:
        cursor.close()


def infer_candidate_key(hint: str, stats: dict[str, dict[str, int]]) -> str:
    item = stats.get(hint)
    if not item:
        return "UNKNOWN"
    num = item.get("cnt_num", 0)
    car = item.get("cnt_car", 0)
    if num > 0 and car == 0:
        return "CODIGO_NUM"
    if car > 0 and num == 0:
        return "CODIGO_CAR"
    if num > 0 and car > 0:
        return "CODIGO_NUM" if num >= car else "CODIGO_CAR"
    return "UNKNOWN"


def build_suggestions(
    *,
    hints: list[dict[str, str]],
    available_multitabla: set[str],
    key_stats: dict[str, dict[str, int]],
) -> dict[str, Any]:
    out: list[dict[str, Any]] = []
    seen: set[tuple[str, str, str]] = set()
    for item in hints:
        key = (item["source_table"], item["source_column"], item["hint"])
        if key in seen:
            continue
        seen.add(key)
        exists = item["hint"] in available_multitabla
        out.append(
            {
                "source_table": item["source_table"],
                "source_column": item["source_column"],
                "candidate_multitabla": item["hint"],
                "candidate_key": infer_candidate_key(item["hint"], key_stats),
                "candidate_description_column": "DESCRIPCION",
                "confidence": "high" if exists else "low",
                "reason": "oracle_comment_hint_exact_match" if exists else "hint_not_found_in_multitabla",
                "approved": False,
            }
        )
    return {"suggested_parametric_mappings": out}


def run(schema: str, tables: list[str], output: str, overwrite: bool = False, project_root: Path = PROJECT_ROOT) -> int:
    settings = get_settings()
    safe_schema = validate_schema_name(schema)
    safe_tables = tables
    output_path = resolve_output_path(output, overwrite=overwrite, project_root=project_root)
    comments_path = (project_root / "metadata" / "generated" / "oracle_comments.yml").resolve()
    comments_payload = load_oracle_comments(comments_path)
    hints = collect_comment_hints(comments_payload, safe_schema, safe_tables)

    connection = None
    try:
        connection = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=_build_dsn(settings),
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        available, key_stats = fetch_multitabla_reference(connection, safe_schema)
        payload = build_suggestions(hints=hints, available_multitabla=available, key_stats=key_stats)
        output_path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")
        print("Estado: OK")
        print(f"suggestions: {len(payload.get('suggested_parametric_mappings', []))}")
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
    parser = argparse.ArgumentParser(description="Descubre candidatos de mapping a MULTITABLA desde comentarios Oracle")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--tables", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--overwrite", action="store_true")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(
        schema=args.schema,
        tables=parse_table_names(args.tables),
        output=args.output,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
