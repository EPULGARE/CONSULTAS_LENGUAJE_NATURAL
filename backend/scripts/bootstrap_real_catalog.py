from __future__ import annotations

import argparse
from pathlib import Path

import yaml

from app.core.config import get_settings
from scripts.inspect_oracle_schema import parse_table_names, resolve_output_path, run_inspection, validate_schema_name
from scripts.review_oracle_catalog import build_review_payload, resolve_approval_output

PROJECT_ROOT = Path(__file__).resolve().parents[1]
PLACEHOLDER_HINTS = ("<", ">", "TU_", "YOUR_", "EJEMPLO", "EXAMPLE")
GENERIC_PROD_DOMAINS = {"TEST", "DEMO", "EXAMPLE"}


def _contains_placeholder(value: str) -> bool:
    upper = value.strip().upper()
    if not upper:
        return True
    return any(hint in upper for hint in PLACEHOLDER_HINTS)


def validate_domain(domain: str, *, app_env: str) -> str:
    clean = domain.strip()
    if not clean:
        raise ValueError("--domain es obligatorio")
    if _contains_placeholder(clean):
        raise ValueError("--domain no acepta placeholders")

    if app_env.strip().lower() == "production" and clean.strip().upper() in GENERIC_PROD_DOMAINS:
        raise ValueError("--domain no puede ser generico en APP_ENV=production")
    return clean


def validate_non_placeholder(value: str, field_name: str) -> str:
    clean = value.strip()
    if not clean:
        raise ValueError(f"{field_name} es obligatorio")
    if _contains_placeholder(clean):
        raise ValueError(f"{field_name} no acepta placeholders")
    return clean


def _write_yaml(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        yaml.safe_dump(payload, handle, sort_keys=False, allow_unicode=False)


def run_bootstrap(
    *,
    schema: str,
    tables_raw: str,
    domain: str,
    generated_output: str,
    approval_output: str,
    dry_run: bool,
    overwrite: bool,
) -> int:
    settings = get_settings()

    safe_schema = validate_non_placeholder(schema, "--schema")
    safe_tables_raw = validate_non_placeholder(tables_raw, "--tables")
    safe_domain = validate_domain(domain, app_env=settings.app_env)
    safe_generated_output = validate_non_placeholder(generated_output, "--generated-output")
    safe_approval_output = validate_non_placeholder(approval_output, "--approval-output")

    parsed_schema = validate_schema_name(safe_schema)
    parsed_tables = parse_table_names(safe_tables_raw)
    if not parsed_tables:
        raise ValueError("--tables no puede estar vacio")

    generated_path = resolve_output_path(safe_generated_output, overwrite=overwrite)
    approval_path = resolve_approval_output(safe_approval_output, overwrite=overwrite)

    print("Estado: START")
    print(f"schema: {parsed_schema}")
    print(f"tables: {','.join(parsed_tables)}")
    print(f"domain: {safe_domain}")
    print(f"generated_output: {generated_path}")
    print(f"approval_output: {approval_path}")

    if dry_run:
        print("dry_run: true")
        _print_next_steps(domain=safe_domain, generated_output=generated_path, approval_output=approval_path)
        return 0

    inspect_status = run_inspection(
        schema=parsed_schema,
        tables=parsed_tables,
        output=str(generated_path),
        overwrite=overwrite,
    )
    if inspect_status != 0:
        return inspect_status

    generated_payload = yaml.safe_load(generated_path.read_text(encoding="utf-8")) or {}
    review_payload = build_review_payload(source_file=str(generated_path.resolve()), generated_payload=generated_payload)
    _write_yaml(approval_path, review_payload)

    print("Estado: OK")
    print("promotion_performed: false")
    print("auto_approval_performed: false")
    _print_next_steps(domain=safe_domain, generated_output=generated_path, approval_output=approval_path)
    return 0


def _print_next_steps(*, domain: str, generated_output: Path, approval_output: Path) -> None:
    print("Proximos pasos manuales:")
    print("1. Revisar approval.")
    print("2. Marcar approved=true.")
    print("3. Marcar allowed_for_query=true.")
    print("4. Completar business_description.")
    print("5. Marcar sensitive/allowed_for_select.")
    print(
        "6. Ejecutar promote_oracle_catalog.py con --require-approval:\n"
        f"   py scripts/promote_oracle_catalog.py --input {generated_output} --approval {approval_output} "
        f"--require-approval --domain {domain} --promote-tables --promote-relationships --dry-run"
    )
    print("7. Ejecutar oracle_catalog_smoke_test.py.")
    print("8. Agregar preguntas reales aprobadas.")
    print("9. Ejecutar evaluate_text_to_sql.py.")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Asistente CLI para bootstrap de catalogo real Oracle")
    parser.add_argument("--schema", required=True, help="Schema Oracle real")
    parser.add_argument("--tables", required=True, help="Lista CSV de tablas reales")
    parser.add_argument("--domain", required=True, help="Dominio real")
    parser.add_argument("--generated-output", required=True, help="Ruta en metadata/generated/")
    parser.add_argument("--approval-output", required=True, help="Ruta en metadata/approvals/")
    parser.add_argument("--dry-run", action="store_true", help="Solo valida parametros y muestra pasos")
    parser.add_argument("--overwrite", action="store_true", help="Permite sobrescribir archivos")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()
    return run_bootstrap(
        schema=args.schema,
        tables_raw=args.tables,
        domain=args.domain,
        generated_output=args.generated_output,
        approval_output=args.approval_output,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )


if __name__ == "__main__":
    raise SystemExit(main())
