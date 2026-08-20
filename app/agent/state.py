"""Agent 状态：保存完整消息历史，逐轮保留 reasoning_content 与 tool_calls。"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Optional


@dataclass
class Turn:
    """一轮交互：模型回复（含推理）与工具执行结果。"""
    assistant_content: Optional[str] = None
    reasoning_content: Optional[str] = None
    tool_calls: list[dict] = field(default_factory=list)   # [{id, name, arguments}]
    tool_results: list[dict] = field(default_factory=list)  # [{tool_call_id, name, output}]
    finish_reason: Optional[str] = None

    @property
    def has_tool_calls(self) -> bool:
        return bool(self.tool_calls)


class AgentState:
    def __init__(self, system_prompt: str, task: str):
        self.system_prompt = system_prompt
        self.task = task
        self.turns: list[Turn] = []
        self.messages: list[dict] = field(default_factory=list)  # 发送给 API 的消息序列
        self.messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": task},
        ]

    def add_assistant(self, turn: Turn) -> None:
        self.turns.append(turn)
        msg: dict[str, Any] = {"role": "assistant", "content": turn.assistant_content}
        # P0-2 修复：将 reasoning_content 写入下一轮 messages，
        # 确保上一轮推理真正参与下一轮 API 请求（DeepSeek API 接受该字段回传）
        if turn.reasoning_content:
            msg["reasoning_content"] = turn.reasoning_content
        if turn.tool_calls:
            msg["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": "function",
                    "function": {"name": tc["name"], "arguments": tc["arguments"]},
                }
                for tc in turn.tool_calls
            ]
        self.messages.append(msg)

    def add_tool_result(self, tool_call_id: str, name: str, output: str) -> None:
        self.messages.append({
            "role": "tool",
            "tool_call_id": tool_call_id,
            "name": name,
            "content": output,
        })

    def reasoning_log(self) -> str:
        """导出全部推理内容（用于日志/报告，保证不丢失）。"""
        parts = []
        for i, turn in enumerate(self.turns, start=1):
            if turn.reasoning_content:
                parts.append(f"--- Turn {i} reasoning ---\n{turn.reasoning_content}")
        return "\n\n".join(parts)
