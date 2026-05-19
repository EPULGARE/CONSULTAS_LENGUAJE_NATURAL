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


def resolve_generated_input(input_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    generated_root = (project_root / "metadata" / "generated").resolve()
    path = Path(input_arg)
    path = (project_root / path).resolve() if not path.is_absolute() else path.resolve()
    if generated_root != path and generated_root not in path.parents:
        raise ValueError("--input debe estar dentro de metadata/generated/")
    if not path.exists():
        raise FileNotFoundError("El archivo de input no existe")
    return path


def resolve_approval_input(approval_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    approvals_root = (project_root / "metadata" / "approvals").resolve()
    path = Path(approval_arg)
    path = (project_root / path).resolve() if not path.is_absolute() else path.resolve()
    if approvals_root != path and approvals_root not in path.parents:
        raise ValueError("--approval debe estar dentro de metadata/approvals/")
    if not path.exists():
        raise FileNotFoundError("El archivo de approval no existe")
    return path


def _normalize_table_entry(table_entry: dict[str, Any], domain: str, approved_column_names: set[str] | None = None) -> dict[str, Any]:
    full_name = str(table_entry.get("full_name", "")).strip()
    if "." not in full_name:
        raise ValueError(f"Tabla invalida en input: {full_name}")
    schema_name, table_name = full_name.split(".", 1)

    columns = []
    for col in table_entry.get("columns", []):
        col_name = col.get("name", "")
        if approved_column_names is not None and col_name not in approved_column_names:
            continue
        columns.append(
            {
                "name": col_name,
                "type": col.get("data_type", col.get("type", "text")),
                "description": col.get("business_description", col.get("description", "")) or "",
                "sensitive": bool(col.get("sensitive", False)),
                "allowed_for_select": bool(col.get("allowed_for_select", True)),
            }
        )

    sensitive_columns = [c["name"] for c in columns if c.get("sensitive")]

    return {
        "schema": schema_name,
        "name": table_name,
        "description": table_entry.get("description", "") or "",
        "domain": domain,
        "synonyms": table_entry.get("synonyms", []) or [],
        "allowed_for_query": bool(table_entry.get("allowed_for_query", True)),
        "sensitive_columns": sensitive_columns,
        "default_filters": table_entry.get("default_filters", []) or [],
        "example_questions": table_entry.get("example_questions", []) or [],
        "columns": columns,
    }


def _normalize_relationships(table_entry: dict[str, Any], approved_relationships: list[dict[str, Any]] | None = None) -> list[dict[str, Any]]:
    source = table_entry.get("full_name", "")
    relationships = []
    source_fks = table_entry.get("foreign_keys", [])
    for fk in source_fks:
        target = fk.get("references_table", "")
        mappings = fk.get("column_mappings", [])
        if approved_relationships is not None:
            allowed = False
            for rel in approved_relationships:
                if rel.get("references_table") == target and rel.get("column_mappings", []) == mappings:
                    allowed = True
                    break
            if not allowed:
                continue

        for mapping in mappings:
            relationships.append(
                {
                    "left_table": source,
                    "left_column": mapping.get("source_column", ""),
                    "right_table": target,
                    "right_column": mapping.get("target_column", ""),
                    "description": "",
                }
            )
    return relationships


def _build_generated_index(generated_tables: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(t.get("full_name", "")): t for t in generated_tables}


def _validated_approved_scope(generated_tables: list[dict[str, Any]], approval_payload: dict[str, Any], input_path: Path) -> dict[str, dict[str, Any]]:
    if approval_payload.get("source_file") != str(input_path):
        raise ValueError("Approval source_file no coincide con --input")

    generated_index = _build_generated_index(generated_tables)
    approved_scope: dict[str, dict[str, Any]] = {}

    for table_review in approval_payload.get("tables", []):
        full_name = table_review.get("full_name", "")
        if full_name not in generated_index:
            raise ValueError("Approval referencia tabla inexistente en generated")

        generated_table = generated_index[full_name]
        generated_cols = {c.get("name") for c in generated_table.get("columns", [])}

        approved_columns = set()
        for col in table_review.get("columns", []):
            col_name = col.get("name")
            if col_name not in generated_cols:
                raise ValueError("Approval referencia columna inexistente en generated")
            if col.get("approved"):
                approved_columns.add(col_name)

        approved_rels = []
        for rel in table_review.get("relationships", []):
            exists = False
            for generated_rel in generated_table.get("foreign_keys", []):
                if (
                    generated_rel.get("references_table") == rel.get("references_table")
                    and generated_rel.get("column_mappings", []) == rel.get("column_mappings", [])
                ):
                    exists = True
                    break
            if not exists:
                raise ValueError("Approval referencia relacion inexistente en generated")
            if rel.get("approved"):
                approved_rels.append(rel)

        if table_review.get("approved") and table_review.get("allowed_for_query"):
            approved_scope[full_name] = {
                "table_review": table_review,
                "approved_columns": approved_columns,
                "approved_relationships": approved_rels,
            }

    return approved_scope


def promote_catalog(
    *,
    input_path: Path,
    domain: str,
    promote_tables: bool,
    promote_relationships: bool,
    dry_run: bool,
    overwrite: bool,
    approval_path: Path | None = None,
    require_approval: bool = False,
    project_root: Path = PROJECT_ROOT,
) -> dict[str, Any]:
    if require_approval and approval_path is None:
        raise ValueError("--require-approval exige --approval")

    metadata_root = project_root / "metadata"
    generated = _load_yaml(input_path)
    generated_tables = generated.get("tables", [])

    approval_payload = _load_yaml(approval_path) if approval_path else None
    approved_scope = None
    if approval_payload is not None:
        approved_scope = _validated_approved_scope(generated_tables, approval_payload, input_path)

    tables_file = metadata_root / "tables.yml"
    relationships_file = metadata_root / "relationships.yml"
    domains_file = metadata_root / "domains.yml"
    business_terms_file = metadata_root / "business_terms.yml"

    tables_list = _load_yaml(tables_file).get("tables", [])
    relationships_list = _load_yaml(relationships_file).get("relationships", [])
    domains_list = _load_yaml(domains_file).get("domains", [])
    business_terms_list = _load_yaml(business_terms_file).get("business_terms", [])

    existing_table_keys = {f"{t.get('schema')}.{t.get('name')}" for t in tables_list}
    existing_rel_keys = {(r.get("left_table"), r.get("left_column"), r.get("right_table"), r.get("right_column")) for r in relationships_list}

    added_tables = 0
    added_relationships = 0

    if promote_tables:
        for table_entry in generated_tables:
            full_name = table_entry.get("full_name", "")
            if approved_scope is not None and full_name not in approved_scope:
                continue

            review_data = approved_scope.get(full_name) if approved_scope is not None else None
            approved_columns = review_data.get("approved_columns") if review_data else None
            normalized = _normalize_table_entry(table_entry, domain, approved_column_names=approved_columns)
            if review_data:
                normalized["allowed_for_query"] = True

            key = f"{normalized['schema']}.{normalized['name']}"
            if key in existing_table_keys:
                continue
            tables_list.append(normalized)
            existing_table_keys.add(key)
            added_tables += 1

    if promote_relationships:
        for table_entry in generated_tables:
            full_name = table_entry.get("full_name", "")
            if approved_scope is not None and full_name not in approved_scope:
                continue

            review_data = approved_scope.get(full_name) if approved_scope is not None else None
            approved_rels = review_data.get("approved_relationships") if review_data else None
            for rel in _normalize_relationships(table_entry, approved_relationships=approved_rels):
                rel_key = (rel["left_table"], rel["left_column"], rel["right_table"], rel["right_column"])
                if rel_key in existing_rel_keys:
                    continue
                relationships_list.append(rel)
                existing_rel_keys.add(rel_key)
                added_relationships += 1

    if domain and domain not in {d.get("name") for d in domains_list}:
        domains_list.append({"name": domain, "description": "", "keywords": []})

    should_write = overwrite and not dry_run
    if should_write:
        _write_yaml(tables_file, {"tables": tables_list})
        _write_yaml(relationships_file, {"relationships": relationships_list})
        _write_yaml(domains_file, {"domains": domains_list})
        _write_yaml(business_terms_file, {"business_terms": business_terms_list})

    return {
        "added_tables": added_tables,
        "added_relationships": added_relationships,
        "dry_run": dry_run,
        "used_approval": approval_path is not None,
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Promociona metadata generada de Oracle al catalogo principal")
    parser.add_argument("--input", required=True, help="Ruta dentro de metadata/generated/")
    parser.add_argument("--approval", required=False, help="Ruta dentro de metadata/approvals/")
    parser.add_argument("--require-approval", action="store_true", help="Exigir approval para promover")
    parser.add_argument("--domain", required=True, help="Dominio de negocio para las tablas promovidas")
    parser.add_argument("--promote-tables", action="store_true", help="Promover tablas")
    parser.add_argument("--promote-relationships", action="store_true", help="Promover relaciones")
    parser.add_argument("--dry-run", action="store_true", help="Simular promocion sin escribir")
    parser.add_argument("--overwrite", action="store_true", help="Aplicar cambios en archivos de metadata")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if not args.promote_tables and not args.promote_relationships:
        raise SystemExit("Debe indicar --promote-tables y/o --promote-relationships")

    if args.require_approval and not args.approval:
        raise SystemExit("--require-approval exige --approval")

    effective_dry_run = True if not args.overwrite else False
    if args.dry_run:
        effective_dry_run = True

    input_path = resolve_generated_input(args.input)
    approval_path = resolve_approval_input(args.approval) if args.approval else None

    result = promote_catalog(
        input_path=input_path,
        domain=args.domain.strip(),
        promote_tables=args.promote_tables,
        promote_relationships=args.promote_relationships,
        dry_run=effective_dry_run,
        overwrite=args.overwrite,
        approval_path=approval_path,
        require_approval=args.require_approval,
    )

    if not args.approval:
        print("WARNING: Promocion sin approval formal. Recomendado usar --approval y --require-approval")

    print("Estado: OK")
    print(f"dry_run: {result['dry_run']}")
    print(f"added_tables: {result['added_tables']}")
    print(f"added_relationships: {result['added_relationships']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
