from __future__ import annotations

from pytest import MonkeyPatch

from liveclip.adapters.llm.client import LLMClient


def test_llm_client_prefers_legacy_llm_api_env(monkeypatch: MonkeyPatch) -> None:
    monkeypatch.setenv("LLM_API", "legacy-key")
    monkeypatch.setenv("LLM_API_KEY", "new-key")

    client = LLMClient()

    assert client._api_key == "legacy-key"


def test_llm_client_retries_without_json_mode_when_provider_rejects_it(
    monkeypatch: MonkeyPatch,
) -> None:
    calls: list[dict[str, object]] = []

    class FakeResponse:
        def __init__(self, status_code: int, text: str, payload: dict[str, object]) -> None:
            self.status_code = status_code
            self.text = text
            self._payload = payload

        def raise_for_status(self) -> None:
            if self.status_code >= 400:
                raise AssertionError("fallback request should avoid raise_for_status")

        def json(self) -> dict[str, object]:
            return self._payload

    def fake_post(
        url: str,
        *,
        headers: dict[str, str],
        json: dict[str, object],
        timeout: int,
    ) -> FakeResponse:
        calls.append(json.copy())
        if len(calls) == 1:
            return FakeResponse(400, "unknown field response_format", {})
        return FakeResponse(
            200,
            "ok",
            {"choices": [{"message": {"content": "{\"ok\": true}"}}]},
        )

    monkeypatch.setattr("liveclip.adapters.llm.client.requests.post", fake_post)

    client = LLMClient(api_key="key", model="model", base_url="https://example.test/v1")
    content = client.chat(
        system_prompt="Return JSON",
        user_prompt="ping",
        json_mode=True,
    )

    assert content == "{\"ok\": true}"
    assert calls[0]["response_format"] == {"type": "json_object"}
    assert "response_format" not in calls[1]
