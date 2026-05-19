from __future__ import annotations

from pathlib import Path
from typing import Any

import yaml

from app.semantic_catalog.models import (
    ApprovedLookupValuesEntry,
    DomainCatalog,
    LookupValueNormalization,
    ParametricMapping,
    RelationshipMetadata,
    StaticValueMapping,
    TableMetadata,
)


class SemanticCatalogLoader:
    def __init__(self, metadata_path: Path) -> None:
        self.metadata_path = metadata_path

    def _load_yaml(self, filename: str) -> dict[str, Any]:
        target = self.metadata_path / filename
        if not target.exists():
            return {}
        return yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    def load_domains(self) -> list[DomainCatalog]:
        data = self._load_yaml("domains.yml")
        return [DomainCatalog(**item) for item in data.get("domains", [])]

    def load_tables(self) -> list[TableMetadata]:
        data = self._load_yaml("tables.yml")
        tables = [TableMetadata(**item) for item in data.get("tables", [])]
        overrides = self.load_business_overrides()
        manual_tables = [TableMetadata(**item) for item in overrides.get("manual_tables", [])]
        table_overrides = overrides.get("tables", {})
        by_full_name = {table.full_name: table for table in tables}
        for manual_table in manual_tables:
            by_full_name[manual_table.full_name] = manual_table

        enriched: list[TableMetadata] = []
        for table in by_full_name.values():
            override = table_overrides.get(table.full_name, {})
            if override:
                table = self._apply_table_override(table, override)
            enriched.append(table)
        return enriched

    def load_relationships(self) -> list[RelationshipMetadata]:
        data = self._load_yaml("relationships.yml")
        relationships = [RelationshipMetadata(**item) for item in data.get("relationships", [])]
        overrides = self.load_business_overrides()
        relationships.extend(RelationshipMetadata(**item) for item in overrides.get("manual_relationships", []))
        return relationships

    def load_examples(self) -> dict[str, list[str]]:
        data = self._load_yaml("examples.yml")
        return data.get("examples", {})

    def load_parametric_mappings(self) -> list[ParametricMapping]:
        overrides = self.load_business_overrides()
        return [ParametricMapping(**item) for item in overrides.get("approved_parametric_mappings", [])]

    def load_static_value_mappings(self) -> list[StaticValueMapping]:
        overrides = self.load_business_overrides()
        return [StaticValueMapping(**item) for item in overrides.get("static_value_mappings", [])]

    def load_lookup_value_normalizations(self) -> list[LookupValueNormalization]:
        target = self.metadata_path / "curated" / "lookup_value_normalization.yml"
        if not target.exists():
            return []
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return [LookupValueNormalization(**item) for item in payload.get("lookup_value_normalization", [])]

    def load_approved_lookup_values(self) -> list[ApprovedLookupValuesEntry]:
        target = self.metadata_path / "generated" / "approved_lookup_values.yml"
        if not target.exists():
            return []
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        return [ApprovedLookupValuesEntry(**item) for item in payload.get("approved_lookup_values", [])]

    def load_numeric_entity_mappings(self) -> list[object]:
        target = self.metadata_path / "curated" / "numeric_entity_mappings.yml"
        if not target.exists():
            return []
        payload = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        from app.semantic_normalization.models import NumericEntityMapping

        return [NumericEntityMapping(**item) for item in payload.get("numeric_entity_mappings", [])]

    def load_oracle_comments(self) -> dict[str, Any]:
        target = self.metadata_path / "generated" / "oracle_comments.yml"
        if not target.exists():
            return {}
        return yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    def load_business_overrides(self) -> dict[str, Any]:
        target = self.metadata_path / "curated" / "business_overrides.yml"
        if not target.exists():
            return {}
        return yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    def load_ambiguity_rules(self) -> dict[str, Any]:
        target = self.metadata_path / "curated" / "ambiguity_rules.yml"
        if not target.exists():
            return {"ambiguities": []}
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(data.get("ambiguities"), list):
            data["ambiguities"] = []
        return data

    def load_ambiguity_learning_suggestions(self) -> dict[str, Any]:
        target = self.metadata_path / "generated" / "ambiguity_learning_suggestions.yml"
        if not target.exists():
            return {"suggestions": []}
        data = yaml.safe_load(target.read_text(encoding="utf-8")) or {}
        if not isinstance(data.get("suggestions"), list):
            data["suggestions"] = []
        return data

    @staticmethod
    def _apply_table_override(table: TableMetadata, override: dict[str, Any]) -> TableMetadata:
        table_data = table.model_dump(by_alias=True)
        if "business_description" in override:
            table_data["description"] = override.get("business_description") or table_data.get("description", "")
        if "synonyms" in override:
            table_data["synonyms"] = override.get("synonyms") or []
        if "domain" in override:
            table_data["domain"] = override.get("domain") or table_data["domain"]
        if "allowed_for_query" in override:
            table_data["allowed_for_query"] = bool(override.get("allowed_for_query"))
        if "sensitive_columns" in override:
            table_data["sensitive_columns"] = [str(c).upper() for c in (override.get("sensitive_columns") or [])]
        if "default_filters" in override:
            table_data["default_filters"] = override.get("default_filters") or []
        if "example_questions" in override:
            table_data["example_questions"] = override.get("example_questions") or []

        column_overrides = (override.get("columns") or {}) if isinstance(override.get("columns"), dict) else {}
        sensitive_set = {c.upper() for c in table_data.get("sensitive_columns", [])}
        updated_columns = []
        for column in table.columns:
            col_data = column.model_dump()
            col_override = column_overrides.get(column.name, {})
            if "business_description" in col_override:
                col_data["description"] = col_override.get("business_description") or col_data.get("description", "")
            if "allowed_for_select" in col_override:
                col_data["allowed_for_select"] = bool(col_override.get("allowed_for_select"))
            col_data["sensitive"] = col_data["name"].upper() in sensitive_set
            updated_columns.append(col_data)

        table_data["columns"] = updated_columns
        return TableMetadata(**table_data)
