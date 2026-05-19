from __future__ import annotations

import argparse
from pathlib import Path

import yaml

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _load_yaml(path: Path) -> dict:
    if not path.exists():
        return {}
    return yaml.safe_load(path.read_text(encoding="utf-8")) or {}


def main() -> int:
    parser = argparse.ArgumentParser(description="Review ambiguity learning suggestions")
    parser.add_argument("--metadata-root", default="metadata", help="Metadata root path")
    args = parser.parse_args()

    metadata_root = (PROJECT_ROOT / args.metadata_root).resolve()
    curated = metadata_root / "curated" / "ambiguity_rules.yml"
    generated = metadata_root / "generated" / "ambiguity_learning_suggestions.yml"

    rules = _load_yaml(curated).get("ambiguities", [])
    suggestions = _load_yaml(generated).get("suggestions", [])

    print("=== AMBIGUITY RULES ===")
    for rule in rules:
        print(f"- phrase={rule.get('phrase')} approved_resolution={rule.get('approved_resolution')} confidence={rule.get('confidence')} requires_confirmation={rule.get('requires_confirmation')}")

    print("\n=== LEARNING SUGGESTIONS ===")
    if not suggestions:
        print("No suggestions yet")
        return 0

    ranked = sorted(suggestions, key=lambda x: int(x.get("count", 0)), reverse=True)
    for item in ranked:
        phrase = item.get("phrase")
        selected = item.get("selected_resolution")
        count = item.get("count", 0)
        timestamp = item.get("timestamp", "")
        print(f"- phrase={phrase} selected_resolution={selected} count={count} timestamp={timestamp}")

    print("\nReview actions:")
    print("1. Promote to approved_resolution in curated/ambiguity_rules.yml")
    print("2. Increase confidence when governed evidence is enough")
    print("3. Keep requires_confirmation=true if still ambiguous")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
