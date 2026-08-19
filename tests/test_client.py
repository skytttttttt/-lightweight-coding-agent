"""DeepSeekClient 解析测试：使用 mock HTTP 传输，验证 reasoning_content 与 tool_calls 保留。"""
import json

import httpx
import pytest

from app.model.client import DeepSeekClient


def _make_client(handler) -> DeepSeekClient:
    c = DeepSeekClient(api_key="test-key", base_url="https://api.deepseek.com",
                       model="deepseek-v4-flash")
    c._client = httpx.Client(transport=httpx.MockTransport(handler))
    return c


def test_parse_with_reasoning_and_tool_calls():
    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        assert body["model"] == "deepseek-v4-flash"
        assert "tools" in body
        payload = {
            "choices": [{
                "message": {
                    "content": None,
                    "reasoning_content": "我需要先查看文件列表",
                    "tool_calls": [{
                        "id": "call_1",
                        "type": "function",
                        "function": {"name": "list_files", "arguments": "{\"path\": \".\"}"},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        }
        return httpx.Response(200, json=payload)

    client = _make_client(handler)
    resp = client.chat([{"role": "user", "content": "hi"}], tools=[{"type": "function"}])
    assert resp.reasoning_content == "我需要先查看文件列表"
    assert len(resp.tool_calls) == 1
    assert resp.tool_calls[0].name == "list_files"
    assert resp.tool_calls[0].arguments == {"path": "."}


def test_parse_final_answer_with_reasoning():
    def handler(request: httpx.Request) -> httpx.Response:
        payload = {
            "choices": [{
                "message": {
                    "content": "完成",
                    "reasoning_content": "确认没有问题了",
                    "tool_calls": None,
                },
                "finish_reason": "stop",
            }]
        }
        return httpx.Response(200, json=payload)

    client = _make_client(handler)
    resp = client.chat([{"role": "user", "content": "hi"}])
    assert resp.content == "完成"
    assert resp.reasoning_content == "确认没有问题了"
    assert resp.tool_calls == []
    assert resp.finish_reason == "stop"


def test_api_error_raises():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    client = _make_client(handler)
    with pytest.raises(RuntimeError, match="DeepSeek API 错误"):
        client.chat([{"role": "user", "content": "hi"}])
