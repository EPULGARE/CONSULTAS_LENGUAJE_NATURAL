from app.semantic_catalog.models import ColumnMetadata, DomainCatalog, TableMetadata
from app.semantic_catalog.readiness import validate_catalog_ready


def test_validate_catalog_ready_empty_catalog_fails():
    result = validate_catalog_ready(domains=[], tables=[])
    assert result.ready is False


def test_validate_catalog_ready_all_disallowed_tables_fails():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=False,
            columns=[ColumnMetadata(name="ID", type="number")],
        )
    ]
    result = validate_catalog_ready(domains=[DomainCatalog(name="domain_alpha", description="x")], tables=tables)
    assert result.ready is False


def test_validate_catalog_ready_all_sensitive_columns_fails():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            sensitive_columns=["SECRET_COL"],
            columns=[
                ColumnMetadata(name="SECRET_COL", type="varchar", sensitive=True, allowed_for_select=True),
            ],
        )
    ]
    result = validate_catalog_ready(domains=[DomainCatalog(name="domain_alpha", description="x")], tables=tables)
    assert result.ready is False


def test_validate_catalog_ready_rejects_sensitive_true_when_other_safe_column_exists():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            columns=[
                ColumnMetadata(name="ID", type="number", sensitive=False, allowed_for_select=True),
                ColumnMetadata(name="SECRET_COL", type="varchar", sensitive=True, allowed_for_select=True),
            ],
        )
    ]

    result = validate_catalog_ready(domains=[DomainCatalog(name="domain_alpha", description="x")], tables=tables)

    assert result.ready is False
    assert any("SECRET_COL" in error for error in result.errors)


def test_validate_catalog_ready_rejects_sensitive_columns_entry_when_selectable():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            sensitive_columns=["SECRET_COL"],
            columns=[
                ColumnMetadata(name="ID", type="number", sensitive=False, allowed_for_select=True),
                ColumnMetadata(name="SECRET_COL", type="varchar", sensitive=False, allowed_for_select=True),
            ],
        )
    ]

    result = validate_catalog_ready(domains=[DomainCatalog(name="domain_alpha", description="x")], tables=tables)

    assert result.ready is False
    assert any("SECRET_COL" in error for error in result.errors)


def test_validate_catalog_ready_accepts_sensitive_column_when_not_selectable():
    tables = [
        TableMetadata(
            schema="TEST_SCHEMA",
            name="TEST_TABLE",
            domain="domain_alpha",
            allowed_for_query=True,
            sensitive_columns=["SECRET_COL"],
            columns=[
                ColumnMetadata(name="ID", type="number", sensitive=False, allowed_for_select=True),
                ColumnMetadata(name="SECRET_COL", type="varchar", sensitive=True, allowed_for_select=False),
            ],
        )
    ]

    result = validate_catalog_ready(domains=[DomainCatalog(name="domain_alpha", description="x")], tables=tables)

    assert result.ready is True
