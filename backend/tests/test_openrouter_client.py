import asyncio
import shutil
import uuid
from pathlib import Path

import pytest

from app.llm.openrouter_client import OpenRouterClient


def _mk_workspace_tmp() -> Path:
    base = Path("backend/tests/_tmp") / str(uuid.uuid4())
    base.mkdir(parents=True, exist_ok=True)
    return base


def test_proxy_is_built_from_env(monkeypatch):
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_enabled", True)
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_host", "proxy.epm.com.co")
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_port", 8080)
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_user", "u")
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_password", "p")
    client = OpenRouterClient()
    proxies = client._build_proxies()
    assert proxies == {"http": "http://u:p@proxy.epm.com.co:8080", "https": "http://u:p@proxy.epm.com.co:8080"}


def test_error_sanitizes_proxy_password(monkeypatch):
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_api_key", "sk-secret")
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_enabled", True)
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_host", "proxy.epm.com.co")
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_port", 8080)
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_user", "user1")
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_proxy_password", "pass1")
    client = OpenRouterClient()

    def _raise(*args, **kwargs):
        raise RuntimeError("proxy auth failed for user1:pass1 and sk-secret")

    monkeypatch.setattr("app.llm.openrouter_client.requests.post", _raise)
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(client.chat_completion(model="m", system_prompt="s", user_prompt="u"))
    text = str(exc.value)
    assert "pass1" not in text
    assert "sk-secret" not in text
    assert "***" in text


def test_verify_uses_ca_cert_if_exists(monkeypatch):
    base = _mk_workspace_tmp()
    try:
        cert = base / "epm-root.cer"
        cert.write_text("dummy", encoding="utf-8")
        monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_ca_cert_path", str(cert))
        monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_insecure", False)
        client = OpenRouterClient()
        assert client._resolve_verify() == str(cert.resolve())
    finally:
        shutil.rmtree(base, ignore_errors=True)


def test_openrouter_insecure_disables_verify(monkeypatch):
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_insecure", True)
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_ca_cert_path", "")
    client = OpenRouterClient()
    assert client._resolve_verify() is False


def test_missing_ca_cert_returns_clear_error(monkeypatch):
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_insecure", False)
    monkeypatch.setattr("app.llm.openrouter_client.settings.openrouter_ca_cert_path", "certs/missing.cer")
    client = OpenRouterClient()
    with pytest.raises(RuntimeError, match="OPENROUTER_CA_CERT_PATH not found"):
        client._resolve_verify()
