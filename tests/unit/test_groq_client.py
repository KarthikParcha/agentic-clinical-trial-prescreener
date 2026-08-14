import asyncio
from collections.abc import Awaitable
from types import SimpleNamespace
from typing import Any

import httpx
import pytest
from groq import APIConnectionError

from clinical_trial_prescreener.config import GroqSettings
from clinical_trial_prescreener.infrastructure.llm.groq_client import (
    GroqClient,
    GroqClientError,
)


def run(coroutine: Awaitable[Any]) -> Any:
    return asyncio.run(coroutine)


class FakeCompletions:
    def __init__(self, response: object) -> None:
        self.response = response
        self.calls: list[dict[str, Any]] = []

    async def create(self, **kwargs: Any) -> object:
        self.calls.append(kwargs)
        if isinstance(self.response, Exception):
            raise self.response
        return self.response


class FakeAsyncGroq:
    def __init__(self, response: object) -> None:
        self.completions = FakeCompletions(response)
        self.chat = SimpleNamespace(completions=self.completions)
        self.closed = False

    async def close(self) -> None:
        self.closed = True


def response_with_content(content: str) -> object:
    return SimpleNamespace(
        choices=[SimpleNamespace(message=SimpleNamespace(content=content))]
    )


def settings(model: str = "test-model") -> GroqSettings:
    return GroqSettings(api_key="test-key", llm_model=model, _env_file=None)


def test_generate_uses_configured_model_and_json_object_mode() -> None:
    sdk = FakeAsyncGroq(response_with_content('{"criteria":[]}'))
    client = GroqClient(settings(), client=sdk)  # type: ignore[arg-type]

    result = run(client.generate(system_prompt="system", user_prompt="user"))

    assert result == '{"criteria":[]}'
    assert sdk.completions.calls == [
        {
            "model": "test-model",
            "messages": [
                {"role": "system", "content": "system"},
                {"role": "user", "content": "user"},
            ],
            "temperature": 0,
            "response_format": {"type": "json_object"},
        }
    ]


def test_groq_settings_support_environment_model_configuration(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "environment-key")
    monkeypatch.setenv("GROQ_LLM_MODEL", "environment-model")

    configured = GroqSettings(_env_file=None)  # type: ignore[call-arg]

    assert configured.api_key.get_secret_value() == "environment-key"
    assert configured.llm_model == "environment-model"


def test_groq_settings_default_model() -> None:
    configured = GroqSettings(api_key="test-key", _env_file=None)

    assert configured.llm_model == "llama-3.3-70b-versatile"


def test_provider_api_failure_becomes_groq_client_error() -> None:
    provider_error = APIConnectionError(
        message="connection failed",
        request=httpx.Request("POST", "https://api.groq.com"),
    )
    sdk = FakeAsyncGroq(provider_error)
    client = GroqClient(settings(), client=sdk)  # type: ignore[arg-type]

    with pytest.raises(GroqClientError, match="Groq request failed"):
        run(client.generate(system_prompt="system", user_prompt="user"))


def test_missing_generated_content_becomes_groq_client_error() -> None:
    sdk = FakeAsyncGroq(response_with_content(""))
    client = GroqClient(settings(), client=sdk)  # type: ignore[arg-type]

    with pytest.raises(GroqClientError, match="no generated content"):
        run(client.generate(system_prompt="system", user_prompt="user"))


def test_aclose_closes_sdk_client() -> None:
    sdk = FakeAsyncGroq(response_with_content('{"criteria":[]}'))
    client = GroqClient(settings(), client=sdk)  # type: ignore[arg-type]

    run(client.aclose())

    assert sdk.closed is True
