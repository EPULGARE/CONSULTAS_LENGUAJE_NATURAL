from __future__ import annotations

import argparse
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


def build_context(metadata_root: Path) -> tuple[dict[str, Any], dict[str, dict[str, Any]]]:
    tables_data = _load_yaml(metadata_root / "tables.yml")
    relationships_data = _load_yaml(metadata_root / "relationships.yml")
    overrides = _load_yaml(metadata_root / "curated" / "business_overrides.yml")
    comments = _load_yaml(metadata_root / "generated" / "oracle_comments.yml")

    tables = list(tables_data.get("tables", [])) + list(overrides.get("manual_tables", []))
    relationships = list(relationships_data.get("relationships", [])) + list(overrides.get("manual_relationships", []))
    mappings = list(overrides.get("approved_parametric_mappings", []))

    by_full_name: dict[str, dict[str, Any]] = {}
    for table in tables:
        full_name = f"{table.get('schema')}.{table.get('name')}"
        by_full_name[full_name] = table

    directory_entries = []
    contexts: dict[str, dict[str, Any]] = {}

    for full_name, table in by_full_name.items():
        domain = table.get("domain", "")
        description = table.get("description", "") or ""
        context_path = f"metadata/context/tables/{full_name}.yml"

        keywords = [str(x).lower() for x in (table.get("synonyms") or []) if str(x).strip()]
        business_terms = [str(x) for x in (table.get("example_questions") or []) if str(x).strip()]

        directory_entries.append(
            {
                "table": full_name,
                "domain": domain,
                "short_description": description,
                "keywords": keywords,
                "business_terms": business_terms,
                "allowed_for_query": bool(table.get("allowed_for_query", True)),
                "context_path": context_path,
            }
        )

        rels_for_table = [
            rel
            for rel in relationships
            if rel.get("left_table") == full_name or rel.get("right_table") == full_name
        ]
        maps_for_table = [
            mp
            for mp in mappings
            if mp.get("source_table") == full_name or mp.get("lookup_table") == full_name
        ]

        comment_section = ((comments.get("tables") or {}).get(full_name) or {}) if isinstance(comments, dict) else {}
        column_comments = (comment_section.get("columns") or {}) if isinstance(comment_section, dict) else {}

        columns = []
        for col in table.get("columns", []):
            name = col.get("name", "")
            columns.append(
                {
                    "name": name,
                    "type": col.get("type", "text"),
                    "business_description": col.get("description", "") or "",
                    "selectable": bool(col.get("allowed_for_select", True)),
                    "sensitive": bool(col.get("sensitive", False)),
                    "synonyms": [],
                    "comments_auxiliary": str((column_comments.get(name) or {}).get("comment") or ""),
                }
            )

        contexts[full_name] = {
            "table": full_name,
            "domain": domain,
            "business_description": description,
            "columns": columns,
            "relationships": rels_for_table,
            "approved_parametric_mappings": maps_for_table,
        }

    directory_entries.sort(key=lambda x: x["table"])
    return {"tables": directory_entries}, contexts


def build_relationship_index(metadata_root: Path) -> dict[str, Any]:
    tables_data = _load_yaml(metadata_root / "tables.yml")
    relationships_data = _load_yaml(metadata_root / "relationships.yml")
    overrides = _load_yaml(metadata_root / "curated" / "business_overrides.yml")

    tables = list(tables_data.get("tables", [])) + list(overrides.get("manual_tables", []))
    relationships = list(relationships_data.get("relationships", [])) + list(overrides.get("manual_relationships", []))
    domain_by_table: dict[str, str] = {}
    for table in tables:
        full = f"{table.get('schema')}.{table.get('name')}".upper()
        domain_by_table[full] = str(table.get("domain", "")).strip()

    index_rows: list[dict[str, Any]] = []
    for rel in relationships:
        from_table = str(rel.get("left_table", "")).upper()
        to_table = str(rel.get("right_table", "")).upper()
        from_column = str(rel.get("left_column", "")).upper()
        to_column = str(rel.get("right_column", "")).upper()
        if not from_table or not to_table or not from_column or not to_column:
            continue
        domains = sorted(
            {
                d
                for d in (
                    domain_by_table.get(from_table, ""),
                    domain_by_table.get(to_table, ""),
                )
                if d
            }
        )
        index_rows.append(
            {
                "from_table": from_table,
                "from_column": from_column,
                "to_table": to_table,
                "to_column": to_column,
                "description": str(rel.get("description", "") or ""),
                "approved": bool(rel.get("approved", True)),
                "join_type": str(rel.get("join_type", "inner") or "inner").lower(),
                "domains": domains,
            }
        )
    return {"relationships": index_rows}


def run(*, overwrite: bool = False, project_root: Path = PROJECT_ROOT) -> int:
    metadata_root = project_root / "metadata"
    context_root = metadata_root / "context"
    table_dir_path = context_root / "table_directory.yml"
    relationship_index_path = context_root / "relationship_index.yml"

    if table_dir_path.exists() and not overwrite:
        raise FileExistsError("table_directory.yml ya existe. Use --overwrite")

    directory_payload, contexts = build_context(metadata_root)
    relationship_index = build_relationship_index(metadata_root)
    _write_yaml(table_dir_path, directory_payload)
    _write_yaml(relationship_index_path, relationship_index)

    for full_name, context_payload in contexts.items():
        path = context_root / "tables" / f"{full_name}.yml"
        if path.exists() and not overwrite:
            continue
        _write_yaml(path, context_payload)

    print("Estado: OK")
    print(f"tables_indexed: {len(directory_payload.get('tables', []))}")
    print(f"context_files: {len(contexts)}")
    print(f"relationship_index: {relationship_index_path}")
    print(f"output_directory: {context_root}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Regenera metadata/context desde el catalogo curado")
    parser.add_argument("--overwrite", action="store_true", help="Sobrescribir archivos de contexto")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(overwrite=args.overwrite)


if __name__ == "__main__":
    raise SystemExit(main())
