from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from app.core.config import get_settings  # noqa: E402
from app.llm.openrouter_client import OpenRouterClient  # noqa: E402


def _sanitize(message: str, api_key: str, proxy_user: str, proxy_password: str) -> str:
    clean = message
    for secret in (api_key, proxy_user, proxy_password):
        if secret:
            clean = clean.replace(secret, "***")
    return clean


async def _probe(model: str) -> str:
    client = OpenRouterClient()
    return await client.chat_completion(
        model=model,
        system_prompt="Responde solo con: OK",
        user_prompt="healthcheck",
    )


def run_health_check(model: str | None = None) -> int:
    settings = get_settings()
    selected_model = (model or settings.openrouter_model_classifier).strip()

    print("Estado: START")
    print(f"base_url: {settings.openrouter_base_url}")
    print(f"timeout_seconds: {settings.openrouter_timeout_seconds}")
    print(f"proxy_enabled: {settings.openrouter_proxy_enabled}")
    print(f"model: {selected_model}")

    try:
        completion = asyncio.run(_probe(selected_model))
        print("Estado: OK")
        print(f"completion_preview: {completion[:120]}")
        return 0
    except Exception as exc:
        print("Estado: ERROR")
        print(
            _sanitize(
                str(exc),
                settings.openrouter_api_key,
                settings.openrouter_proxy_user,
                settings.openrouter_proxy_password,
            )
        )
        return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Valida conexion OpenRouter con proxy/certificado desde .env")
    parser.add_argument("--model", required=False, help="Modelo a probar; default OPENROUTER_MODEL_CLASSIFIER")
    args = parser.parse_args()
    return run_health_check(model=args.model)


if __name__ == "__main__":
    raise SystemExit(main())
