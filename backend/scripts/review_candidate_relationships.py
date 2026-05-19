from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Any

import oracledb

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.relationship_feedback import (  # noqa: E402
    RelationshipCandidate,
    RelationshipCandidateReview,
    collect_candidate_evidence,
    load_candidate_payload,
    score_candidate_relationship,
    write_review_payload,
)
from app.semantic_catalog.loader import SemanticCatalogLoader  # noqa: E402


def resolve_input_path(input_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    generated_root = (project_root / "metadata" / "generated").resolve()
    input_path = Path(input_arg)
    input_path = (project_root / input_path).resolve() if not input_path.is_absolute() else input_path.resolve()
    if generated_root != input_path and generated_root not in input_path.parents:
        raise ValueError("--input debe estar dentro de metadata/generated/")
    if not input_path.exists():
        raise FileNotFoundError("El archivo de input no existe")
    return input_path


def resolve_output_path(output_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    approvals_root = (project_root / "metadata" / "approvals").resolve()
    approvals_root.mkdir(parents=True, exist_ok=True)
    output_path = Path(output_arg)
    output_path = (project_root / output_path).resolve() if not output_path.is_absolute() else output_path.resolve()
    if approvals_root != output_path and approvals_root not in output_path.parents:
        raise ValueError("--output debe estar dentro de metadata/approvals/")
    return output_path


def build_dsn(settings: Any) -> str:
    if settings.db_sid:
        return oracledb.makedsn(settings.db_host, settings.db_port, sid=settings.db_sid)
    return oracledb.makedsn(settings.db_host, settings.db_port, service_name=settings.db_service_name)


def column_type_lookup(loader: SemanticCatalogLoader) -> dict[tuple[str, str], str]:
    lookup: dict[tuple[str, str], str] = {}
    for table in loader.load_tables():
        for column in table.columns:
            lookup[(table.full_name.upper(), column.name.upper())] = column.type
    return lookup


def run(*, input_path: Path, output_path: Path) -> int:
    settings = get_settings()
    loader = SemanticCatalogLoader(settings.metadata_path)
    type_lookup = column_type_lookup(loader)
    payload = load_candidate_payload(input_path)
    candidates = [RelationshipCandidate(**item) for item in payload.get("candidate_relationships", [])]

    connection = None
    try:
        connection = oracledb.connect(
            user=settings.db_user,
            password=settings.db_password,
            dsn=build_dsn(settings),
            tcp_connect_timeout=settings.db_timeout_seconds,
        )
        reviews: list[RelationshipCandidateReview] = []
        for candidate in candidates:
            from_type = type_lookup.get((candidate.from_table.upper(), candidate.from_column.upper()))
            to_type = type_lookup.get((candidate.to_table.upper(), candidate.to_column.upper()))
            evidence = collect_candidate_evidence(
                connection,
                candidate,
                from_column_type=from_type,
                to_column_type=to_type,
            )
            hydrated = candidate.model_copy(update={"evidence": evidence})
            score = score_candidate_relationship(hydrated)
            reviews.append(
                RelationshipCandidateReview(
                    **hydrated.model_dump(mode="json"),
                    score=score,
                    approved=False,
                    reviewer_notes="",
                )
            )

        write_review_payload(output_path, reviews)
        print("Estado: OK")
        print(f"input: {input_path}")
        print(f"output: {output_path}")
        print(f"candidates: {len(reviews)}")
        return 0
    except Exception as exc:
        message = str(exc)
        if settings.db_password:
            message = message.replace(settings.db_password, "***")
        print("Estado: ERROR")
        print(message)
        return 1
    finally:
        if connection is not None:
            connection.close()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Genera un archivo de review con evidencia para relaciones candidatas")
    parser.add_argument("--input", required=True, help="Archivo generado dentro de metadata/generated/")
    parser.add_argument("--output", required=True, help="Archivo de review dentro de metadata/approvals/")
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return run(
        input_path=resolve_input_path(args.input),
        output_path=resolve_output_path(args.output),
    )


if __name__ == "__main__":
    raise SystemExit(main())
