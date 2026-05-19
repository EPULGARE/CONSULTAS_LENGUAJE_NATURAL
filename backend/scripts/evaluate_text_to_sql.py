from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.evaluation.evaluator import TextToSQLEvaluator


def resolve_output_path(output_arg: str, project_root: Path = PROJECT_ROOT) -> Path:
    outputs_root = (project_root / "outputs").resolve()
    outputs_root.mkdir(parents=True, exist_ok=True)

    output_path = Path(output_arg)
    if not output_path.is_absolute():
        output_path = (project_root / output_path).resolve()
    else:
        output_path = output_path.resolve()

    if outputs_root != output_path and outputs_root not in output_path.parents:
        raise ValueError("--output debe estar dentro de outputs/")
    return output_path


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Evalua calidad de SQL generado en modo dry-run")
    parser.add_argument("--questions", required=True, help="Ruta de questions.yml")
    parser.add_argument("--output", required=True, help="Ruta de salida en outputs/")
    parser.add_argument("--fail-on-error", action="store_true", help="Retorna codigo 1 si hay fallas")
    parser.add_argument("--domain", required=False, help="Filtrar por dominio")
    parser.add_argument("--limit", type=int, required=False, help="Limitar cantidad de preguntas")
    parser.add_argument("--enable-intent-enhancer", action="store_true", help="Activa intent_enhancer en evaluacion (disabled por defecto)")
    return parser


def main() -> int:
    parser = build_parser()
    args = parser.parse_args()

    if args.limit is not None and args.limit <= 0:
        raise SystemExit("--limit debe ser mayor que 0")

    questions_path = Path(args.questions)
    if not questions_path.is_absolute():
        questions_path = (PROJECT_ROOT / questions_path).resolve()
    else:
        questions_path = questions_path.resolve()

    output_path = resolve_output_path(args.output)

    evaluator = TextToSQLEvaluator(
        questions_path=questions_path,
        domain_filter=args.domain,
        limit=args.limit,
        enable_intent_enhancer=args.enable_intent_enhancer,
    )
    report = evaluator.evaluate()

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(report.model_dump_json(indent=2), encoding="utf-8")

    print("Estado: OK")
    print(f"total_questions: {report.total_questions}")
    print(f"passed: {report.passed}")
    print(f"failed: {report.failed}")
    print(f"skipped: {report.skipped}")
    print(f"pass_rate: {report.pass_rate}")
    print(f"output: {output_path}")

    if args.fail_on_error and report.failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
