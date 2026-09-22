from __future__ import annotations

from dataclasses import dataclass, field

from app.semantic_catalog.models import DomainCatalog, TableMetadata


@dataclass
class CatalogReadinessResult:
    ready: bool
    errors: list[str] = field(default_factory=list)


def validate_catalog_ready(domains: list[DomainCatalog], tables: list[TableMetadata]) -> CatalogReadinessResult:
    errors: list[str] = []

    if not tables:
        errors.append("No tables found in semantic catalog.")
        return CatalogReadinessResult(ready=False, errors=errors)

    seen_tables: set[str] = set()
    duplicate_tables: set[str] = set()
    for table in tables:
        full_name = table.full_name.upper()
        if full_name in seen_tables:
            duplicate_tables.add(full_name)
        seen_tables.add(full_name)
        _collect_duplicate_columns(table, errors)
        _collect_sensitive_selectability_errors(table, errors)

    if duplicate_tables:
        errors.append(f"Duplicate tables found: {', '.join(sorted(duplicate_tables))}")

    has_domain_in_tables = any(bool((table.domain or "").strip()) for table in tables)
    if not domains and not has_domain_in_tables:
        errors.append("No domains found and no domain assigned to tables.")

    allowed_tables = [table for table in tables if table.allowed_for_query]
    if not allowed_tables:
        errors.append("No table marked as allowed_for_query=true.")
    else:
        has_selectable = any(_has_at_least_one_selectable_non_sensitive_column(table) for table in allowed_tables)
        if not has_selectable:
            errors.append("No allowed table has at least one selectable non-sensitive column.")

    return CatalogReadinessResult(ready=not errors, errors=errors)


def _collect_duplicate_columns(table: TableMetadata, errors: list[str]) -> None:
    seen_columns: set[str] = set()
    duplicate_columns: set[str] = set()
    for column in table.columns:
        name = column.name.upper()
        if name in seen_columns:
            duplicate_columns.add(name)
        seen_columns.add(name)
    if duplicate_columns:
        errors.append(
            f"Duplicate columns found in table {table.full_name}: {', '.join(sorted(duplicate_columns))}"
        )


def _collect_sensitive_selectability_errors(table: TableMetadata, errors: list[str]) -> None:
    sensitive_names = {name.upper() for name in table.sensitive_columns}
    conflicting_columns = sorted(
        {
            column.name.upper()
            for column in table.columns
            if column.allowed_for_select
            and (column.sensitive or column.name.upper() in sensitive_names)
        }
    )
    if conflicting_columns:
        errors.append(
            f"Sensitive columns cannot be selectable in table {table.full_name}: "
            f"{', '.join(conflicting_columns)}"
        )


def _has_at_least_one_selectable_non_sensitive_column(table: TableMetadata) -> bool:
    sensitive_names = {name.upper() for name in table.sensitive_columns}
    for column in table.columns:
        if not column.allowed_for_select:
            continue
        if column.sensitive:
            continue
        if column.name.upper() in sensitive_names:
            continue
        return True
    return False
