from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def resolve_input_path(input_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    approvals_root = (project_root / "metadata" / "approvals").resolve()
    input_path = Path(input_arg)
    input_path = (project_root / input_path).resolve() if not input_path.is_absolute() else input_path.resolve()
    if approvals_root != input_path and approvals_root not in input_path.parents:
        raise ValueError("--input debe estar dentro de metadata/approvals/")
    if not input_path.exists():
        raise FileNotFoundError("El archivo de input no existe")
    return input_path


def promote_relationships(*, input_path: Path, overwrite: bool, project_root: Path = PROJECT_ROOT) -> dict[str, int]:
    metadata_root = project_root / "metadata"
    review_payload = _load_yaml(input_path)
    relationships_file = metadata_root / "relationships.yml"
    relationships_payload = _load_yaml(relationships_file)
    relationships = list(relationships_payload.get("relationships", []))
    existing = {
        (
            str(item.get("left_table", "")).upper(),
            str(item.get("left_column", "")).upper(),
            str(item.get("right_table", "")).upper(),
            str(item.get("right_column", "")).upper(),
        )
        for item in relationships
    }

    added = 0
    for item in review_payload.get("candidate_relationships", []):
        if not item.get("approved"):
            continue
        rel = {
            "left_table": item.get("from_table"),
            "left_column": item.get("from_column"),
            "right_table": item.get("to_table"),
            "right_column": item.get("to_column"),
            "description": item.get("reviewer_notes", "") or "Relacion promovida desde relationship_candidates_review",
        }
        key = (
            str(rel["left_table"]).upper(),
            str(rel["left_column"]).upper(),
            str(rel["right_table"]).upper(),
            str(rel["right_column"]).upper(),
        )
        if key in existing:
            continue
        relationships.append(rel)
        existing.add(key)
        added += 1

    if overwrite:
        _write_yaml(relationships_file, {"relationships": relationships})
    return {"added_relationships": added}


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promueve relaciones aprobadas desde relationship_candidates_review.yml")
    parser.add_argument("--input", required=True, help="Archivo de review dentro de metadata/approvals/")
    parser.add_argument("--overwrite", action="store_true", help="Aplicar cambios en metadata/relationships.yml")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    result = promote_relationships(
        input_path=resolve_input_path(args.input),
        overwrite=args.overwrite,
    )
    print("Estado: OK")
    print(f"added_relationships: {result['added_relationships']}")
    print("Siguiente paso sugerido: py scripts/build_context_from_catalog.py --overwrite")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
