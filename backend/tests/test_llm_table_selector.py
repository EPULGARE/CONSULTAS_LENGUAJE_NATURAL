import asyncio
import warnings

from app.context_selector.llm_table_selector import select_tables_with_llm
from app.context_selector.models import DirectoryEntry


class GoodClient:
    async def chat_completion(self, **kwargs):
        return '{"selected_tables": ["SAC.CLIENTES", "SAC.MUNICIPIOS"], "reason": "municipio", "confidence": 0.9}'


class MixedClient:
    async def chat_completion(self, **kwargs):
        return '{"selected_tables": ["SAC.CLIENTES", "SAC.INEXISTENTE", "SAC.BLOQUEADA"], "reason": "x", "confidence": 0.9}'


class FailingClient:
    async def chat_completion(self, **kwargs):
        raise RuntimeError("network")


def _directory():
    return [
        DirectoryEntry(
            table="SAC.CLIENTES",
            domain="clientes",
            short_description="",
            keywords=["cliente"],
            business_terms=[],
            allowed_for_query=True,
            context_path="metadata/context/tables/SAC.CLIENTES.yml",
        ),
        DirectoryEntry(
            table="SAC.MUNICIPIOS",
            domain="clientes",
            short_description="",
            keywords=["armenia"],
            business_terms=[],
            allowed_for_query=True,
            context_path="metadata/context/tables/SAC.MUNICIPIOS.yml",
        ),
        DirectoryEntry(
            table="SAC.BLOQUEADA",
            domain="clientes",
            short_description="",
            keywords=["x"],
            business_terms=[],
            allowed_for_query=False,
            context_path="metadata/context/tables/SAC.BLOQUEADA.yml",
        ),
    ]


def test_llm_selector_parses_valid_json():
    result = select_tables_with_llm("usuarios en armenia", _directory(), ["SAC.CLIENTES"], client=GoodClient())
    assert "SAC.CLIENTES" in result.selected_tables
    assert "SAC.MUNICIPIOS" in result.selected_tables


def test_llm_selector_ignores_unknown_and_blocked_tables():
    result = select_tables_with_llm("x", _directory(), ["SAC.CLIENTES"], client=MixedClient())
    assert "SAC.INEXISTENTE" not in result.selected_tables
    assert "SAC.BLOQUEADA" not in result.selected_tables


def test_llm_selector_fallback_on_error():
    result = select_tables_with_llm("x", _directory(), ["SAC.CLIENTES"], client=FailingClient())
    assert result.used_fallback is True
    assert result.selected_tables == ["SAC.CLIENTES"]


def test_llm_selector_no_unawaited_warning_inside_running_loop():
    async def _runner():
        with warnings.catch_warnings(record=True) as captured:
            warnings.simplefilter("always")
            result = select_tables_with_llm("usuarios en armenia", _directory(), ["SAC.CLIENTES"], client=GoodClient())
            assert "SAC.CLIENTES" in result.selected_tables
        assert not any("was never awaited" in str(w.message) for w in captured)

    asyncio.run(_runner())
