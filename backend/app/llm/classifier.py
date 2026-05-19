from __future__ import annotations

from typing import Any

import yaml

from app.core.config import settings
from app.llm.openrouter_client import OpenRouterClient
from app.llm.prompts import CLASSIFIER_SYSTEM_PROMPT, build_classifier_user_prompt
from app.semantic_catalog.models import DomainCatalog


class DomainClassifier:
    def __init__(self, client: OpenRouterClient | None = None) -> None:
        self.client = client or OpenRouterClient()

    @staticmethod
    def classify_by_rules(question: str, domains: list[DomainCatalog]) -> str | None:
        lower_question = question.lower()
        for domain in domains:
            if any(keyword.lower() in lower_question for keyword in domain.keywords):
                return domain.name
        return None

    @staticmethod
    def _load_domain_vocabulary() -> dict[str, Any]:
        target = settings.metadata_path / "curated" / "domain_vocabulary.yml"
        if not target.exists():
            return {}
        return yaml.safe_load(target.read_text(encoding="utf-8")) or {}

    @staticmethod
    def classify_by_vocabulary(question: str, domains: list[DomainCatalog]) -> str | None:
        allowed_domains = {domain.name for domain in domains}
        raw = DomainClassifier._load_domain_vocabulary()
        entries = (raw.get("domains") or {}) if isinstance(raw.get("domains"), dict) else {}
        if not entries:
            return None

        lower_question = question.lower()
        scores: dict[str, int] = {}
        for domain_name, payload in entries.items():
            if domain_name not in allowed_domains or not isinstance(payload, dict):
                continue

            terms: list[str] = []
            for key in ("canonical_terms", "synonyms", "related_terms"):
                values = payload.get(key, [])
                if isinstance(values, list):
                    terms.extend(str(v).strip().lower() for v in values if str(v).strip())

            score = 0
            for term in terms:
                if term and term in lower_question:
                    score += 1
            if score > 0:
                scores[domain_name] = score

        if not scores:
            return None

        max_score = max(scores.values())
        winners = [domain for domain, score in scores.items() if score == max_score]
        if len(winners) == 1:
            return winners[0]
        return None

    async def classify(self, question: str, domains: list[DomainCatalog]) -> str:
        if not domains:
            raise ValueError("No semantic metadata available for query generation.")

        local_vocab = self.classify_by_vocabulary(question, domains)
        if local_vocab:
            return local_vocab

        local = self.classify_by_rules(question, domains)
        if local:
            return local

        prompt = build_classifier_user_prompt(question, domains)
        result = await self.client.chat_completion(
            model=settings.openrouter_model_classifier,
            system_prompt=CLASSIFIER_SYSTEM_PROMPT,
            user_prompt=prompt,
        )
        allowed = {d.name for d in domains}
        if result in allowed:
            return result
        raise ValueError("No se pudo clasificar el dominio con seguridad")
