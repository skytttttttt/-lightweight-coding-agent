"""DeepSeek API Client。

基于 OpenAI 兼容的 chat/completions 接口，直接解析 JSON，
确保 reasoning_content（Thinking）在每轮 tool call 中完整保留、不丢失。

模型固定为配置中的 DEEPSEEK_MODEL（默认 deepseek-v4-flash），
绝不自行切换模型；模型不可用时停止并报告。
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from typing import Any, Optional

import httpx


@dataclass
class ToolCall:
    id: str
    name: str
    arguments: dict


@dataclass
class ModelResponse:
    content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: list[ToolCall] = field(default_factory=list)
    finish_reason: Optional[str] = None


class DeepSeekClient:
    def __init__(self, api_key: str, base_url: str, model: str, timeout: float = 120.0):
        if not api_key:
            raise ValueError("缺少 DEEPSEEK_API_KEY")
        self.api_key = api_key
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.timeout = timeout
        self._client = httpx.Client(timeout=timeout)

    def _endpoint(self) -> str:
        # 兼容 base_url 已含 /v1 或需追加 /v1 两种情况
        if self.base_url.endswith("/chat/completions"):
            return self.base_url
        if self.base_url.endswith("/v1"):
            return f"{self.base_url}/chat/completions"
        return f"{self.base_url}/v1/chat/completions"

    def chat(self, messages: list[dict], tools: Optional[list[dict]] = None,
             max_retries: int = 2) -> ModelResponse:
        """调用模型。网络瞬时故障（连接断开/超时/5xx）自动重试最多 max_retries 次；
        认证或模型错误不重试，立即抛错。"""
        payload: dict[str, Any] = {
            "model": self.model,
            "messages": messages,
            "stream": False,
        }
        if tools:
            payload["tools"] = tools
            payload["tool_choice"] = "auto"

        last_err: Exception | None = None
        for attempt in range(max_retries + 1):
            try:
                resp = self._client.post(self._endpoint(), headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                }, json=payload)
            except (httpx.TransportError, httpx.TimeoutException) as e:
                last_err = e
                if attempt < max_retries:
                    time.sleep(1.5 * (attempt + 1))
                    continue
                raise RuntimeError(f"DeepSeek API 网络错误: {e}") from e

            if resp.status_code == 200:
                return self._parse(resp.json())
            # 认证/模型/参数错误不重试
            if resp.status_code in (401, 403, 404, 422):
                raise RuntimeError(
                    f"DeepSeek API 错误 status={resp.status_code}: {resp.text[:500]}"
                )
            last_err = RuntimeError(
                f"DeepSeek API 错误 status={resp.status_code}: {resp.text[:500]}"
            )
            if attempt < max_retries:
                time.sleep(1.5 * (attempt + 1))
        raise last_err

    def _parse(self, data: dict) -> ModelResponse:
        choice = data["choices"][0]
        msg = choice.get("message", {})
        tool_calls: list[ToolCall] = []
        for tc in msg.get("tool_calls") or []:
            try:
                args = json.loads(tc["function"].get("arguments") or "{}")
            except json.JSONDecodeError:
                args = {"_raw": tc["function"].get("arguments", "")}
            tool_calls.append(ToolCall(
                id=tc.get("id", ""),
                name=tc["function"]["name"],
                arguments=args,
            ))
        return ModelResponse(
            content=msg.get("content"),
            reasoning_content=msg.get("reasoning_content"),
            tool_calls=tool_calls,
            finish_reason=choice.get("finish_reason"),
        )

    def close(self) -> None:
        self._client.close()
