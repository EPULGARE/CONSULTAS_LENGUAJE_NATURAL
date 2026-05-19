from __future__ import annotations

import argparse
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def resolve_generated_input(input_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    generated_root = (project_root / "metadata" / "generated").resolve()
    path = Path(input_arg)
    path = (project_root / path).resolve() if not path.is_absolute() else path.resolve()

    if generated_root != path and generated_root not in path.parents:
        raise ValueError("--input debe estar dentro de metadata/generated/")
    if not path.exists():
        raise FileNotFoundError("El archivo de input no existe")
    return path


def resolve_approval_output(output_arg: str, project_root: Path = PROJECT_ROOT, overwrite: bool = False) -> Path:
    approvals_root = (project_root / "metadata" / "approvals").resolve()
    path = Path(output_arg)
    path = (project_root / path).resolve() if not path.is_absolute() else path.resolve()

    if approvals_root != path and approvals_root not in path.parents:
        raise ValueError("--output debe estar dentro de metadata/approvals/")
    if path.exists() and not overwrite:
        raise FileExistsError("El archivo de output ya existe. Use --overwrite")
    return path


def build_review_payload(*, source_file: str, generated_payload: dict[str, Any]) -> dict[str, Any]:
    review_tables = []
    for table in generated_payload.get("tables", []):
        relationships = []
        for fk in table.get("foreign_keys", []):
            relationships.append(
                {
                    "approved": False,
                    "references_table": fk.get("references_table", ""),
                    "column_mappings": fk.get("column_mappings", []),
                }
            )

        columns = []
        for column in table.get("columns", []):
            columns.append(
                {
                    "name": column.get("name", ""),
                    "approved": False,
                    "business_description": "",
                    "sensitive": False,
                    "allowed_for_select": True,
                }
            )

        review_tables.append(
            {
                "full_name": table.get("full_name", ""),
                "approved": False,
                "allowed_for_query": False,
                "domain": "",
                "business_description": "",
                "columns": columns,
                "relationships": relationships,
            }
        )

    return {
        "source_file": source_file,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "reviewer": "",
        "status": "pending",
        "tables": review_tables,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genera archivo de revision formal para metadata Oracle")
    parser.add_argument("--input", required=True, help="Ruta dentro de metadata/generated/")
    parser.add_argument("--output", required=True, help="Ruta dentro de metadata/approvals/")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescribir archivo de salida")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    input_path = resolve_generated_input(args.input)
    output_path = resolve_approval_output(args.output, overwrite=args.overwrite)

    generated = _load_yaml(input_path)
    review = build_review_payload(source_file=str(input_path), generated_payload=generated)
    _write_yaml(output_path, review)

    print("Estado: OK")
    print(f"source_file: {input_path}")
    print(f"output: {output_path}")
    print(f"tables: {len(review.get('tables', []))}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
