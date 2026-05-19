import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from app.core.config import settings
from app.llm.classifier import DomainClassifier
from app.semantic_catalog.models import DomainCatalog


class FakeClient:
    def __init__(self, response: str) -> None:
        self.response = response
        self.called = 0

    async def chat_completion(self, **kwargs):
        self.called += 1
        return self.response


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def _write_vocab(base: Path, body: str) -> Path:
    metadata_path = base / "metadata"
    curated = metadata_path / "curated"
    curated.mkdir(parents=True, exist_ok=True)
    (curated / "domain_vocabulary.yml").write_text(body, encoding="utf-8")
    return metadata_path


def test_rule_based_classification():
    domains = [
        DomainCatalog(name="domain_alpha", description="x", keywords=["alpha", "metric"]),
        DomainCatalog(name="domain_beta", description="y", keywords=["beta"]),
    ]
    question = "Necesito metricas alpha del periodo"
    result = DomainClassifier.classify_by_rules(question, domains)
    assert result == "domain_alpha"


def test_generation_blocked_without_catalog():
    classifier = DomainClassifier(client=None)

    async def _run():
        await classifier.classify("anything", [])

    with pytest.raises(ValueError, match="No semantic metadata available for query generation."):
        asyncio.run(_run())


def test_vocabulary_usuarios_classifies_clientes_locally(monkeypatch):
    base = _mk_workspace_tmp()
    try:
        metadata_path = _write_vocab(
            base,
            """
domains:
  clientes:
    canonical_terms: [cliente, clientes]
    synonyms: [usuario, usuarios, abonado, suscriptor]
    related_terms: [estado cliente, estrato, municipio, tarifa, saldo]
    tables: [SAC.CLIENTES, SAC.MULTITABLA]
""".strip()
            + "\n",
        )
        monkeypatch.setattr(settings, "metadata_path", metadata_path)

        fake_client = FakeClient("clientes")
        classifier = DomainClassifier(client=fake_client)
        domains = [DomainCatalog(name="clientes", description="", keywords=[])]
        result = asyncio.run(classifier.classify("listar usuarios activos", domains))

        assert result == "clientes"
        assert fake_client.called == 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_vocabulary_abonados_classifies_clientes_locally(monkeypatch):
    base = _mk_workspace_tmp()
    try:
        metadata_path = _write_vocab(
            base,
            """
domains:
  clientes:
    canonical_terms: [cliente, clientes]
    synonyms: [usuario, usuarios, abonado, suscriptor]
    related_terms: [estado cliente, estrato, municipio, tarifa, saldo]
    tables: [SAC.CLIENTES, SAC.MULTITABLA]
""".strip()
            + "\n",
        )
        monkeypatch.setattr(settings, "metadata_path", metadata_path)

        fake_client = FakeClient("clientes")
        classifier = DomainClassifier(client=fake_client)
        domains = [DomainCatalog(name="clientes", description="", keywords=[])]
        result = asyncio.run(classifier.classify("resumen de abonados", domains))

        assert result == "clientes"
        assert fake_client.called == 0
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_tie_uses_openrouter(monkeypatch):
    base = _mk_workspace_tmp()
    try:
        metadata_path = _write_vocab(
            base,
            """
domains:
  clientes:
    canonical_terms: [saldo]
    synonyms: []
    related_terms: []
    tables: [SAC.CLIENTES, SAC.MULTITABLA]
  domain_beta:
    canonical_terms: [saldo]
    synonyms: []
    related_terms: []
    tables: [SAC.CLIENTES]
""".strip()
            + "\n",
        )
        monkeypatch.setattr(settings, "metadata_path", metadata_path)

        fake_client = FakeClient("clientes")
        classifier = DomainClassifier(client=fake_client)
        domains = [
            DomainCatalog(name="clientes", description="", keywords=[]),
            DomainCatalog(name="domain_beta", description="", keywords=[]),
        ]
        result = asyncio.run(classifier.classify("mostrar saldo", domains))

        assert result == "clientes"
        assert fake_client.called == 1
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_no_match_uses_openrouter(monkeypatch):
    base = _mk_workspace_tmp()
    try:
        metadata_path = _write_vocab(
            base,
            """
domains:
  clientes:
    canonical_terms: [cliente]
    synonyms: [usuario]
    related_terms: [estado cliente]
    tables: [SAC.CLIENTES, SAC.MULTITABLA]
""".strip()
            + "\n",
        )
        monkeypatch.setattr(settings, "metadata_path", metadata_path)

        fake_client = FakeClient("clientes")
        classifier = DomainClassifier(client=fake_client)
        domains = [DomainCatalog(name="clientes", description="", keywords=[])]
        result = asyncio.run(classifier.classify("consulta financiera general", domains))

        assert result == "clientes"
        assert fake_client.called == 1
    finally:
        shutil.rmtree(base, ignore_errors=True)
