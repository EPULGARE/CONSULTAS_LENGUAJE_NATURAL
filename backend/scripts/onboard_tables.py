from __future__ import annotations

import argparse
import subprocess
import sys
from pathlib import Path
from typing import Any

import yaml

from scripts import build_context_from_catalog, extract_oracle_comments, inspect_oracle_schema, promote_oracle_catalog, review_oracle_catalog

PROJECT_ROOT = Path(__file__).resolve().parents[1]
SENSITIVE_TOKENS = {
    "NOMBRE",
    "DIRECCION",
    "TELEFONO",
    "CORREO",
    "NIT",
    "DOCUMENTO",
    "GPS",
    "LATITUD",
    "LONGITUD",
    "PERSONA_ID",
    "MATRICULA",
    "FICHA_CATASTRAL",
}
KEY_CANDIDATE_PATTERNS = (
    "CLIENTE_ID",
    "MEDIDOR_ID",
    "MUNICIPIO",
    "DEPTO",
    "CICLO",
    "TARIFA",
    "ESTADO_",
    "_ID",
    "CODIGO_",
    "NRO_",
    "NUMERO_",
)


def _load_yaml(path: Path) -> dict[str, Any]:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def _write_yaml(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(yaml.safe_dump(payload, sort_keys=False, allow_unicode=False), encoding="utf-8")


def _slug_tables(tables: list[str]) -> str:
    return "_".join([t.lower() for t in tables])


def _is_sensitive_column(column_name: str) -> bool:
    upper_name = column_name.upper()
    return any(token in upper_name for token in SENSITIVE_TOKENS)


def _sensitivity_reason(column_name: str) -> str:
    upper_name = column_name.upper()
    for token in SENSITIVE_TOKENS:
        if token in upper_name:
            return f"Coincide patron sensible: {token}"
    return "No aplica"


def _is_key_candidate(column_name: str) -> bool:
    upper_name = column_name.upper()
    return any(pattern in upper_name for pattern in KEY_CANDIDATE_PATTERNS)


def resolve_checklist_output_path(path_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    outputs_root = (project_root / "outputs").resolve()
    path = Path(path_arg)
    path = (project_root / path).resolve() if not path.is_absolute() else path.resolve()
    if outputs_root != path and outputs_root not in path.parents:
        raise ValueError("--checklist-output debe estar dentro de outputs/")
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def apply_auto_approve_safe_columns(approval_path: Path, domain: str) -> dict[str, Any]:
    payload = _load_yaml(approval_path)
    for table in payload.get("tables", []):
        table["approved"] = True
        table["allowed_for_query"] = True
        table["domain"] = domain
        for col in table.get("columns", []):
            sensitive = _is_sensitive_column(str(col.get("name", "")))
            col["sensitive"] = sensitive
            if sensitive:
                col["approved"] = False
                col["allowed_for_select"] = False
            else:
                col["approved"] = True
                col["allowed_for_select"] = True
        for rel in table.get("relationships", []):
            rel["approved"] = False
    _write_yaml(approval_path, payload)
    return payload


def _approval_has_promotable_table(payload: dict[str, Any]) -> bool:
    for table in payload.get("tables", []):
        if table.get("approved") and table.get("allowed_for_query"):
            return True
    return False


def _build_checklist_text(
    *,
    domain: str,
    generated_payload: dict[str, Any],
    approval_payload: dict[str, Any],
    comments_payload: dict[str, Any],
) -> str:
    lines: list[str] = []
    lines.append(f"# Checklist de Onboarding ({domain})")
    lines.append("")
    lines.append("## 1. Tablas procesadas")

    approval_by_table = {t.get("full_name", ""): t for t in approval_payload.get("tables", [])}
    total_fk = 0
    for table in generated_payload.get("tables", []):
        full_name = str(table.get("full_name", ""))
        approval_table = approval_by_table.get(full_name, {})
        table_status = (
            "approved"
            if approval_table.get("approved") and approval_table.get("allowed_for_query")
            else "pending"
        )
        fk_list = table.get("foreign_keys", [])
        total_fk += len(fk_list)
        lines.append(
            f"- {full_name}: columnas={len(table.get('columns', []))}, "
            f"pk={len(table.get('primary_keys', []))}, fk={len(fk_list)}, estado={table_status}"
        )

    lines.append("")
    lines.append("## 2. Columnas sensibles detectadas")
    found_sensitive = False
    for table in approval_payload.get("tables", []):
        full_name = str(table.get("full_name", ""))
        for col in table.get("columns", []):
            col_name = str(col.get("name", ""))
            if _is_sensitive_column(col_name) or bool(col.get("sensitive")):
                found_sensitive = True
                lines.append(
                    f"- {full_name}.{col_name}: razon={_sensitivity_reason(col_name)}, "
                    f"allowed_for_select={str(col.get('allowed_for_select', False)).lower()}"
                )
    if not found_sensitive:
        lines.append("- Sin columnas sensibles detectadas por patron.")

    lines.append("")
    lines.append("## 3. Columnas candidatas a llaves de negocio")
    found_candidates = False
    for table in generated_payload.get("tables", []):
        full_name = str(table.get("full_name", ""))
        for col in table.get("columns", []):
            col_name = str(col.get("name", ""))
            if _is_key_candidate(col_name):
                found_candidates = True
                lines.append(f"- {full_name}.{col_name}")
    if not found_candidates:
        lines.append("- Sin candidatas detectadas por patron.")

    lines.append("")
    lines.append("## 4. Relaciones FK detectadas")
    for table in approval_payload.get("tables", []):
        full_name = str(table.get("full_name", ""))
        for rel in table.get("relationships", []):
            ref = str(rel.get("references_table", ""))
            mappings = rel.get("column_mappings", [])
            mapping_txt = ", ".join(
                [f"{m.get('source_column')}={m.get('target_column')}" for m in mappings if m.get("source_column")]
            )
            status = "aprobada" if rel.get("approved") else "pendiente de confirmar"
            lines.append(f"- {full_name} -> {ref} [{mapping_txt}] estado={status}")
    if total_fk == 0:
        lines.append("- Sin relaciones FK detectadas.")

    lines.append("")
    lines.append("## 5. Relaciones de negocio faltantes a confirmar")
    suggested_questions: list[str] = []
    for table in generated_payload.get("tables", []):
        full_name = str(table.get("full_name", ""))
        for col in table.get("columns", []):
            col_name = str(col.get("name", ""))
            if _is_key_candidate(col_name):
                suggested_questions.append(
                    f"¿{full_name}.{col_name} se relaciona con otra tabla de negocio/catalogo? (especificar destino)"
                )
    if suggested_questions:
        for question in sorted(set(suggested_questions))[:25]:
            lines.append(f"- {question}")
    else:
        lines.append("- Sin preguntas de relacion adicionales generadas por patrones.")

    lines.append("")
    lines.append("## 6. Parametrizaciones sugeridas por comentario Oracle")
    comments_tables = comments_payload.get("tables", {}) if isinstance(comments_payload, dict) else {}
    found_comment_hints = False
    for full_name, data in comments_tables.items():
        columns = (data or {}).get("columns", {}) if isinstance(data, dict) else {}
        for col_name, col_info in columns.items():
            comment_hint = str((col_info or {}).get("comment", "")).strip()
            if comment_hint:
                found_comment_hints = True
                lines.append(
                    f"- {full_name}.{col_name}: comment_hint=\"{comment_hint}\" | "
                    "estado=sugerencia (NO mapping aprobado) | "
                    "pregunta=¿Debe convertirse en approved_parametric_mapping?"
                )
    if not found_comment_hints:
        lines.append("- Sin hints de comentario Oracle para parametrizacion.")

    lines.append("")
    lines.append("## 7. Preguntas minimas para el usuario")
    for table in generated_payload.get("tables", []):
        full_name = str(table.get("full_name", ""))
        lines.append(f"- ¿Que representa la tabla {full_name}?")
        lines.append(f"- ¿Cual es su llave principal de negocio en {full_name}?")
    lines.append("- ¿Que columnas se pueden mostrar al usuario?")
    lines.append("- ¿Que columnas son sensibles?")
    lines.append("- ¿Que relaciones deben aprobarse?")
    lines.append("- ¿Algun campo debe traducirse con MULTITABLA?")
    lines.append("")
    return "\n".join(lines)


def _summarize(generated_path: Path, approval_path: Path, comments_path: Path) -> None:
    generated = _load_yaml(generated_path)
    approval = _load_yaml(approval_path)
    comments = _load_yaml(comments_path)

    table_count = len(generated.get("tables", []))
    column_count = sum(len(t.get("columns", [])) for t in generated.get("tables", []))
    pk_count = sum(len(t.get("primary_keys", [])) for t in generated.get("tables", []))
    fk_count = sum(len(t.get("foreign_keys", [])) for t in generated.get("tables", []))

    sensitive_candidates = []
    for table in approval.get("tables", []):
        for col in table.get("columns", []):
            if _is_sensitive_column(str(col.get("name", ""))):
                sensitive_candidates.append(f"{table.get('full_name')}.{col.get('name')}")

    print("=== RESUMEN ONBOARDING ===")
    print(f"tablas: {table_count}")
    print(f"columnas: {column_count}")
    print(f"pk: {pk_count}")
    print(f"fk: {fk_count}")
    print(f"sensitive_candidates: {len(sensitive_candidates)}")
    for item in sensitive_candidates[:20]:
        print(f"- {item}")

    print("=== PREGUNTAS DE CURADURIA ===")
    for table in generated.get("tables", []):
        for fk in table.get("foreign_keys", []):
            for mapping in fk.get("column_mappings", []):
                print(
                    f"Confirma relacion: {table.get('full_name')}.{mapping.get('source_column')} = "
                    f"{fk.get('references_table')}.{mapping.get('target_column')}"
                )
                print(f"¿Que significa la llave {mapping.get('source_column')}?")

    if isinstance(comments, dict) and comments.get("tables"):
        print("=== COMENTARIOS ORACLE DETECTADOS ===")
        for full_name, info in list((comments.get("tables") or {}).items())[:10]:
            table_comment = (info or {}).get("table_comment", "")
            if table_comment:
                print(f"- {full_name}: {table_comment}")


def run_onboarding(
    *,
    schema: str,
    tables: list[str],
    domain: str,
    overwrite: bool = False,
    auto_approve_safe_columns: bool = False,
    promote: bool = False,
    dry_run: bool = True,
    checklist_output: str | None = None,
    project_root: Path = PROJECT_ROOT,
) -> int:
    slug = _slug_tables(tables)
    generated_rel = f"metadata/generated/{slug}.yml"
    approval_rel = f"metadata/approvals/{slug}_review.yml"
    comments_rel = "metadata/generated/oracle_comments.yml"

    inspect_code = inspect_oracle_schema.run_inspection(
        schema=schema,
        tables=tables,
        output=generated_rel,
        overwrite=overwrite,
    )
    if inspect_code != 0:
        return inspect_code

    review_input = review_oracle_catalog.resolve_generated_input(generated_rel, project_root=project_root)
    review_output = review_oracle_catalog.resolve_approval_output(approval_rel, project_root=project_root, overwrite=overwrite)
    generated_payload = _load_yaml(review_input)
    review_payload = review_oracle_catalog.build_review_payload(source_file=str(review_input), generated_payload=generated_payload)
    _write_yaml(review_output, review_payload)

    extract_code = extract_oracle_comments.run(
        schema=schema,
        tables=tables,
        output=comments_rel,
        overwrite=overwrite,
    )
    if extract_code != 0:
        return extract_code

    if auto_approve_safe_columns:
        apply_auto_approve_safe_columns(review_output, domain)

    build_context_from_catalog.run(overwrite=True, project_root=project_root)

    comments_path = project_root / comments_rel
    _summarize(generated_path=review_input, approval_path=review_output, comments_path=comments_path)
    approval_payload = _load_yaml(review_output)
    comments_payload = _load_yaml(comments_path)
    checklist_text = _build_checklist_text(
        domain=domain,
        generated_payload=generated_payload,
        approval_payload=approval_payload,
        comments_payload=comments_payload,
    )
    print("\n=== CHECKLIST MINIMO ===")
    print(checklist_text)
    if checklist_output:
        checklist_path = resolve_checklist_output_path(checklist_output, project_root=project_root)
        checklist_path.write_text(checklist_text, encoding="utf-8")
        print(f"checklist_output: {checklist_path}")

    if not promote:
        print("Promocion omitida por defecto. Use --promote para aplicar al catalogo principal.")
        return 0

    if not _approval_has_promotable_table(approval_payload):
        raise ValueError("No hay tablas aprobadas para promocion en approval")

    effective_dry_run = dry_run and not overwrite
    if effective_dry_run:
        print("Promocion en dry-run: no se escribiran cambios al catalogo principal")

    promote_oracle_catalog.promote_catalog(
        input_path=review_input,
        approval_path=review_output,
        require_approval=True,
        domain=domain,
        promote_tables=True,
        promote_relationships=True,
        dry_run=effective_dry_run,
        overwrite=overwrite,
        project_root=project_root,
    )

    build_context_from_catalog.run(overwrite=True, project_root=project_root)

    print("Ejecutando smoke test de catalogo...")
    smoke = subprocess.run([sys.executable, "scripts/project_readiness_check.py"], cwd=str(project_root), capture_output=True, text=True)
    print(smoke.stdout.strip())

    print("Ejecutando pytest...")
    test_run = subprocess.run([sys.executable, "-m", "pytest", "-q", "tests"], cwd=str(project_root))
    return test_run.returncode


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Onboarding gobernado de tablas Oracle")
    parser.add_argument("--schema", required=True)
    parser.add_argument("--tables", required=True, help="Lista separada por coma")
    parser.add_argument("--domain", required=True)
    parser.add_argument("--overwrite", action="store_true")
    parser.add_argument("--auto-approve-safe-columns", action="store_true")
    parser.add_argument("--promote", action="store_true")
    parser.add_argument("--dry-run", dest="dry_run", action="store_true", default=True)
    parser.add_argument("--no-dry-run", dest="dry_run", action="store_false")
    parser.add_argument("--checklist-output", required=False, help="Ruta markdown dentro de outputs/")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    tables = inspect_oracle_schema.parse_table_names(args.tables)
    return run_onboarding(
        schema=inspect_oracle_schema.validate_schema_name(args.schema),
        tables=tables,
        domain=args.domain,
        overwrite=args.overwrite,
        auto_approve_safe_columns=args.auto_approve_safe_columns,
        promote=args.promote,
        dry_run=args.dry_run,
        checklist_output=args.checklist_output,
    )


if __name__ == "__main__":
    raise SystemExit(main())
