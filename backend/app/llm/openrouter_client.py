from __future__ import annotations

import asyncio
import warnings
from pathlib import Path
from typing import Any

import requests

from app.core.config import settings


class OpenRouterClient:
    def __init__(self) -> None:
        self.base_url = settings.openrouter_base_url.rstrip("/")
        self.api_key = settings.openrouter_api_key
        self.timeout = settings.openrouter_timeout_seconds
        self.proxy_enabled = settings.openrouter_proxy_enabled
        self.proxy_host = settings.openrouter_proxy_host.strip()
        self.proxy_port = settings.openrouter_proxy_port
        self.proxy_user = settings.openrouter_proxy_user
        self.proxy_password = settings.openrouter_proxy_password
        self.ca_cert_path = settings.openrouter_ca_cert_path.strip()
        self.insecure = settings.openrouter_insecure

    async def chat_completion(self, *, model: str, system_prompt: str, user_prompt: str) -> str:
        if not self.api_key:
            raise RuntimeError("OPENROUTER_API_KEY is not configured")

        payload: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            "temperature": 0,
        }
        headers = {
            "Authorization": f"Bearer {self.api_key}",
            "Content-Type": "application/json",
        }

        try:
            data = await asyncio.to_thread(self._post_json, payload=payload, headers=headers)
        except Exception as exc:
            raise RuntimeError(self._sanitize_error(str(exc))) from exc

        return data["choices"][0]["message"]["content"].strip()

    def _post_json(self, *, payload: dict[str, Any], headers: dict[str, str]) -> dict[str, Any]:
        response = requests.post(
            self._resolve_chat_completions_url(),
            json=payload,
            headers=headers,
            timeout=self.timeout,
            proxies=self._build_proxies(),
            verify=self._resolve_verify(),
        )
        response.raise_for_status()
        return response.json()

    def _resolve_chat_completions_url(self) -> str:
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        return f"{self.base_url}/chat/completions"

    def _build_proxies(self) -> dict[str, str] | None:
        if not self.proxy_enabled:
            return None
        if not self.proxy_host:
            raise RuntimeError("OPENROUTER_PROXY_ENABLED=true but OPENROUTER_PROXY_HOST is empty")

        auth = ""
        if self.proxy_user:
            auth = self.proxy_user
            if self.proxy_password:
                auth = f"{auth}:{self.proxy_password}"
            auth = f"{auth}@"
        proxy_url = f"http://{auth}{self.proxy_host}:{self.proxy_port}"
        return {"http": proxy_url, "https": proxy_url}

    def _resolve_verify(self) -> bool | str:
        if self.insecure:
            warnings.warn("OPENROUTER_INSECURE=1 enabled; TLS verification disabled", RuntimeWarning, stacklevel=2)
            return False
        if self.ca_cert_path:
            cert_path = Path(self.ca_cert_path)
            if not cert_path.is_absolute():
                cwd_candidate = cert_path.resolve()
                if cwd_candidate.exists():
                    cert_path = cwd_candidate
                else:
                    project_candidate = (settings.project_root / cert_path).resolve()
                    cert_path = project_candidate
            if not cert_path.exists():
                raise RuntimeError(f"OPENROUTER_CA_CERT_PATH not found: {cert_path}")
            return str(cert_path)
        return True

    def _sanitize_error(self, message: str) -> str:
        clean = message
        for secret in (self.api_key, self.proxy_user, self.proxy_password):
            if secret:
                clean = clean.replace(secret, "***")
        return clean
