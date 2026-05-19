from scripts import check_openrouter_connection as script


def test_check_script_sanitizes_error(monkeypatch, capsys):
    monkeypatch.setattr("scripts.check_openrouter_connection.get_settings", lambda: type("S", (), {
        "openrouter_model_classifier": "google/gemini-2.5-flash",
        "openrouter_base_url": "https://openrouter.ai/api/v1/chat/completions",
        "openrouter_timeout_seconds": 45,
        "openrouter_proxy_enabled": True,
        "openrouter_api_key": "sk-secret",
        "openrouter_proxy_user": "user1",
        "openrouter_proxy_password": "pass1",
    })())

    async def _boom(model: str) -> str:
        raise RuntimeError("failed sk-secret user1 pass1")

    monkeypatch.setattr("scripts.check_openrouter_connection._probe", _boom)
    status = script.run_health_check()
    out = capsys.readouterr().out
    assert status == 1
    assert "Estado: ERROR" in out
    assert "sk-secret" not in out
    assert "pass1" not in out
