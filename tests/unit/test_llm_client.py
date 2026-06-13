from __future__ import annotations

from pytest import MonkeyPatch

from liveclip.adapters.llm.client import LLMClient


def test_llm_client_prefers_legacy_llm_api_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API", "legacy-key")
    monkeypatch.setenv("LLM_API_KEY", "new-key")

    client = LLMClient()

    assert client._api_key == "legacy-key"
