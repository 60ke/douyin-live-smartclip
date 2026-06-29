from __future__ import annotations

import base64
from pathlib import Path

import httpx

from liveclip.adapters.gpt_image import GPTImageClient, GPTImageInput
from liveclip.config.settings import GPTImageConfig, GPTImageProviderConfig


def test_gpt_image_edit_posts_multipart_and_decodes_b64(
    tmp_path: Path,
    monkeypatch,
) -> None:
    image_a = tmp_path / "template.png"
    image_b = tmp_path / "frame.png"
    image_a.write_bytes(b"\x89PNG\r\n\x1a\n" + b"a" * 16)
    image_b.write_bytes(b"\x89PNG\r\n\x1a\n" + b"b" * 16)
    result_payload = b"\x89PNG\r\n\x1a\nresult"
    captured: dict[str, object] = {}

    def fake_post(url, *, data, files, headers, timeout):  # noqa: ANN001
        captured["url"] = url
        captured["data"] = data
        captured["files"] = files
        captured["headers"] = headers
        captured["timeout"] = timeout
        return httpx.Response(
            200,
            json={
                "data": [
                    {
                        "b64_json": base64.b64encode(result_payload).decode("ascii"),
                    }
                ]
            },
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = GPTImageClient(
        GPTImageConfig(
            api_key="test-key",
            base_url="https://example.test",
            edit_path="/v1/images/edits",
            model="gpt-image-2",
            quality="low",
            timeout_seconds=123,
        )
    )

    result = client.edit(
        images=[
            GPTImageInput(path=image_a, filename="template.png", content_type="image/png"),
            GPTImageInput(path=image_b, filename="frame.png", content_type="image/png"),
        ],
        prompt="生成封面",
        size="1152x2048",
    )

    assert result == result_payload
    assert captured["url"] == "https://example.test/v1/images/edits"
    assert captured["data"] == {
        "model": "gpt-image-2",
        "prompt": "生成封面",
        "quality": "low",
        "n": "1",
        "size": "1152x2048",
    }
    assert captured["headers"] == {"Authorization": "Bearer test-key"}
    assert captured["timeout"] == 123
    files = captured["files"]
    assert isinstance(files, list)
    assert [field for field, _ in files] == ["image", "image"]


def test_gpt_image_edit_falls_back_to_backup_provider(tmp_path: Path, monkeypatch) -> None:
    image = tmp_path / "avatar.png"
    image.write_bytes(b"\x89PNG\r\n\x1a\n" + b"a" * 16)
    result_payload = b"\x89PNG\r\n\x1a\nbackup"
    urls: list[str] = []

    def fake_post(url, *, data, files, headers, timeout):  # noqa: ANN001, ARG001
        urls.append(url)
        if "primary.test" in url:
            return httpx.Response(500, json={"error": {"message": "primary unavailable"}})
        return httpx.Response(
            200,
            json={"data": [{"b64_json": base64.b64encode(result_payload).decode("ascii")}]},
        )

    monkeypatch.setattr(httpx, "post", fake_post)
    client = GPTImageClient(
        GPTImageConfig(
            timeout_seconds=123,
            providers=[
                GPTImageProviderConfig(
                    name="primary",
                    api_key="primary-key",
                    base_url="https://primary.test",
                ),
                GPTImageProviderConfig(
                    name="backup",
                    api_key="backup-key",
                    base_url="https://backup.test",
                ),
            ],
        )
    )

    result = client.edit(
        images=[GPTImageInput(path=image, filename="avatar.png", content_type="image/png")],
        prompt="换背景",
    )

    assert result == result_payload
    assert urls == [
        "https://primary.test/v1/images/edits",
        "https://backup.test/v1/images/edits",
    ]
