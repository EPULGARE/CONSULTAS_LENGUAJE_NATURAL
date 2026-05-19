from __future__ import annotations

from pathlib import Path

import yaml

from app.relationship_feedback.evidence import (
    build_distinct_count_query,
    build_match_distinct_query,
    build_sample_query,
)
from app.relationship_feedback.models import DetectedRelationshipJoin, RelationshipCandidate, RelationshipEvidence
from app.relationship_feedback.scorer import score_candidate_relationship
from app.relationship_feedback.writer import generated_candidates_path, record_relationship_candidates
from scripts.promote_approved_relationships import promote_relationships


def test_record_relationship_candidates_writes_generated_file_without_touching_relationships(tmp_path: Path):
    metadata_root = tmp_path / "metadata"
    (metadata_root / "generated").mkdir(parents=True)
    relationships_path = metadata_root / "relationships.yml"
    relationships_path.write_text(
        yaml.safe_dump(
            {
                "relationships": [
                    {
                        "left_table": "SAC.MEDIDORES",
                        "left_column": "CLIENTE_ID",
                        "right_table": "SAC.CLIENTES",
                        "right_column": "CLIENTE_ID",
                        "description": "Relacion aprobada",
                    }
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = record_relationship_candidates(
        [DetectedRelationshipJoin(from_table="SAC.CLIENTES", from_column="CLIENTE_ID", to_table="SAC.PROCESOS", to_column="CODIGO_CUENTA")],
        question="Cuantos medidores instalados tienen un proceso de Conexion del Servicio",
        blocked_reason="UNAPPROVED_JOIN_PATH",
        metadata_path=metadata_root,
    )

    payload = yaml.safe_load(generated_candidates_path(metadata_root).read_text(encoding="utf-8"))
    assert len(payload["candidate_relationships"]) == 1
    assert payload["candidate_relationships"][0]["from_table"] == "SAC.CLIENTES"
    assert "CODIGO_CUENTA" in payload["candidate_relationships"][0]["to_column"]
    assert result.candidates[0].approved is False
    untouched = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    assert len(untouched["relationships"]) == 1


def test_evidence_queries_use_count_distinct_and_limited_sample():
    assert "COUNT(DISTINCT CLIENTE_ID)" in build_distinct_count_query("SAC.CLIENTES", "CLIENTE_ID")
    assert "COUNT(DISTINCT f.CLIENTE_ID)" in build_match_distinct_query(
        "SAC.CLIENTES",
        "CLIENTE_ID",
        "SAC.PROCESOS",
        "CODIGO_CUENTA",
        distinct_side="from",
    )
    assert "FETCH FIRST 20 ROWS ONLY" in build_sample_query(
        "SAC.CLIENTES",
        "CLIENTE_ID",
        "SAC.PROCESOS",
        "CODIGO_CUENTA",
    )


def test_incompatible_types_score_as_invalid():
    candidate = RelationshipCandidate(
        from_table="SAC.CLIENTES",
        from_column="CLIENTE_ID",
        to_table="SAC.PROCESOS",
        to_column="CODIGO_CUENTA",
        evidence=RelationshipEvidence(
            sampled=True,
            source_distinct_count=100,
            target_distinct_count=100,
            matched_distinct_count=99,
            reverse_matched_distinct_count=99,
            coverage_percent=0.99,
            reverse_coverage_percent=0.99,
            from_column_type="NUMBER",
            to_column_type="VARCHAR2",
        ),
    )
    score = score_candidate_relationship(candidate)
    assert score.candidate_strength == "invalid"


def test_high_score_still_requires_manual_approval():
    candidate = RelationshipCandidate(
        from_table="SAC.CLIENTES",
        from_column="CLIENTE_ID",
        to_table="SAC.PROCESOS",
        to_column="CODIGO_CUENTA",
        approved=False,
        evidence=RelationshipEvidence(
            sampled=True,
            source_distinct_count=100,
            target_distinct_count=100,
            matched_distinct_count=98,
            reverse_matched_distinct_count=90,
            coverage_percent=0.98,
            reverse_coverage_percent=0.90,
            from_column_type="NUMBER",
            to_column_type="NUMBER",
            null_rate_from=0.0,
            null_rate_to=0.0,
        ),
    )
    score = score_candidate_relationship(candidate)
    assert score.candidate_strength == "high"
    assert candidate.approved is False


def test_promote_only_approved_relationships(tmp_path: Path):
    metadata_root = tmp_path / "metadata"
    approvals_root = metadata_root / "approvals"
    approvals_root.mkdir(parents=True)
    relationships_path = metadata_root / "relationships.yml"
    relationships_path.write_text(yaml.safe_dump({"relationships": []}, sort_keys=False), encoding="utf-8")
    review_path = approvals_root / "relationship_candidates_review.yml"
    review_path.write_text(
        yaml.safe_dump(
            {
                "candidate_relationships": [
                    {
                        "from_table": "SAC.CLIENTES",
                        "from_column": "CLIENTE_ID",
                        "to_table": "SAC.PROCESOS",
                        "to_column": "CODIGO_CUENTA",
                        "approved": True,
                        "reviewer_notes": "match alto",
                    },
                    {
                        "from_table": "SAC.CLIENTES",
                        "from_column": "MUNICIPIO",
                        "to_table": "SAC.PROCESOS",
                        "to_column": "DEPTO",
                        "approved": False,
                        "reviewer_notes": "",
                    },
                ]
            },
            sort_keys=False,
        ),
        encoding="utf-8",
    )

    result = promote_relationships(input_path=review_path, overwrite=True, project_root=tmp_path)

    payload = yaml.safe_load(relationships_path.read_text(encoding="utf-8"))
    assert result["added_relationships"] == 1
    assert len(payload["relationships"]) == 1
    assert payload["relationships"][0]["left_table"] == "SAC.CLIENTES"
