"""Agent Loop：核心循环（最大 30 turns，不丢 reasoning_content，含 Repair 协议）。"""
from __future__ import annotations

import json
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from app.agent.prompt import build_system_prompt
from app.agent.state import AgentState, Turn
from app.model.client import DeepSeekClient
from app.tools.registry import ToolRegistry


@dataclass
class AgentResult:
    task: str
    final_answer: str = ""
    turns_used: int = 0
    stopped_by: str = "completed"  # completed / max_turns / repair_limit / error
    repair_attempts: int = 0
    error: str = ""
    log_path: str = ""
    completed: bool = False
    reasoning_log: str = ""
    trace: list = field(default_factory=list)  # 每轮执行轨迹（推理/工具调用/工具结果）


ProgressCallback = Callable[[str, dict], None] | None


class AgentLoop:
    def __init__(self, client: DeepSeekClient, registry: ToolRegistry,
                 max_turns: int = 30, max_repairs: int = 2, log_dir: Path | None = None,
                 progress_callback: ProgressCallback = None):
        self.client = client
        self.registry = registry
        self.max_turns = max_turns
        self.max_repairs = max_repairs
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.progress_callback = progress_callback

    # ---------- 进度回调 ----------
    def _emit(self, event: str, payload: dict) -> None:
        if self.progress_callback:
            try:
                self.progress_callback(event, payload)
            except Exception:  # noqa: BLE001
                pass

    # ---------- 修复状态跟踪 ----------
    @staticmethod
    def _is_failure(output: str) -> bool:
        """判断工具结果是否为失败（error / 测试失败）。"""
        return output.strip().startswith("[error]") or "exit_code=" in output and "exit_code=0" not in output

    def run(self, task: str, system_prompt: str | None = None,
            cancel_event: threading.Event | None = None) -> AgentResult:
        """运行 Agent。

        cancel_event（可选）：外部设置该事件即可请求取消本次运行（Stop / SSE 断开 / 超时）。
        这是 cancellation glue：不改变正常执行逻辑；检测到取消时立即停止，
        不再调用模型、不再执行工具、不再修改文件。
        """
        prompt = system_prompt or build_system_prompt()
        state = AgentState(prompt, task)
        result = AgentResult(task=task)
        repair_attempts = 0
        last_failed = False

        def _cancelled() -> bool:
            return cancel_event is not None and cancel_event.is_set()

        def _cancel_result() -> AgentResult:
            result.stopped_by = "cancelled"
            result.error = "运行已被用户取消（Stop）"
            result.log_path = self._save_log(state, result)
            return result

        for turn_no in range(1, self.max_turns + 1):
            if _cancelled():
                return _cancel_result()
            result.turns_used = turn_no
            # 调用模型
            try:
                resp = self.client.chat(state.messages, tools=self.registry.schemas())
            except Exception as e:  # noqa: BLE001
                result.stopped_by = "error"
                result.error = f"模型调用失败: {e}"
                result.log_path = self._save_log(state, result)
                return result

            turn = Turn(
                assistant_content=resp.content,
                reasoning_content=resp.reasoning_content,
                finish_reason=resp.finish_reason,
                tool_calls=[
                    {"id": tc.id, "name": tc.name, "arguments": json.dumps(tc.arguments, ensure_ascii=False)}
                    for tc in resp.tool_calls
                ],
            )
            state.add_assistant(turn)

            self._emit("thinking", {
                "turn": turn_no,
                "content": resp.content,
                "reasoning": resp.reasoning_content,
                "tool_calls": turn.tool_calls,
                "finish_reason": resp.finish_reason,
            })

            # cancellation glue：模型调用期间用户取消（Stop）时，即使模型已返回，也不允许
            # 把"最终答案"当成正常完成——必须立即停止并返回 CANCELLED（不写文件/不再调工具）。
            if _cancelled():
                return _cancel_result()

            # 无 tool_calls -> 最终答案
            if not resp.tool_calls:
                result.final_answer = resp.content or ""
                result.repair_attempts = repair_attempts
                result.completed = True
                result.log_path = self._save_log(state, result)
                return result

            # 执行工具
            any_failure = False
            for tc in resp.tool_calls:
                if _cancelled():
                    return _cancel_result()
                self._emit("tool_start", {"turn": turn_no, "tool": tc.name, "arguments": tc.arguments,
                                          "tool_call_id": tc.id})
                output = self.registry.execute(tc.name, tc.arguments)
                state.add_tool_result(tc.id, tc.name, output)
                turn.tool_results.append({"tool_call_id": tc.id, "name": tc.name, "output": output})
                success = not self._is_failure(output)
                self._emit("tool_end", {"turn": turn_no, "tool": tc.name, "output": output, "success": success,
                                        "tool_call_id": tc.id})
                if not success:
                    any_failure = True

            if _cancelled():
                return _cancel_result()
            self._emit("turn_complete", {"turn": turn_no, "any_failure": any_failure})

            # Repair 协议：连续失败自动修复，同一问题最多 2 次
            if any_failure:
                if last_failed:
                    repair_attempts += 1
                    self._emit("repair", {"turn": turn_no, "attempt": repair_attempts, "max_repairs": self.max_repairs})
                    if repair_attempts >= self.max_repairs:
                        result.stopped_by = "repair_limit"
                        result.error = f"连续失败超过 {self.max_repairs} 次，停止自动修复"
                        result.repair_attempts = repair_attempts
                        result.log_path = self._save_log(state, result)
                        return result
                last_failed = True
            else:
                last_failed = False

            time.sleep(0.1)

        # 达到最大轮次
        result.stopped_by = "max_turns"
        result.error = f"达到最大轮次 {self.max_turns}"
        result.repair_attempts = repair_attempts
        result.log_path = self._save_log(state, result)
        return result

    # ---------- 日志 ----------
    def _save_log(self, state: AgentState, result: AgentResult) -> str:
        ts = time.strftime("%Y%m%d_%H%M%S")
        path = self.log_dir / f"run_{ts}.json"
        reasoning = state.reasoning_log()
        result.reasoning_log = reasoning
        # 导出每轮执行轨迹（推理 + 工具调用 + 工具结果），供 Web 页面展示
        result.trace = [
            {
                "turn": i,
                "content": turn.assistant_content,
                "reasoning": turn.reasoning_content,
                "tool_calls": [
                    {"name": tc["name"], "arguments": tc.get("arguments", "{}")}
                    for tc in turn.tool_calls
                ],
                "tool_results": [
                    {"name": tr["name"], "output": tr["output"]}
                    for tr in turn.tool_results
                ],
                "finish_reason": turn.finish_reason,
            }
            for i, turn in enumerate(state.turns, start=1)
        ]
        payload = {
            "task": result.task,
            "completed": result.completed,
            "stopped_by": result.stopped_by,
            "turns_used": result.turns_used,
            "repair_attempts": result.repair_attempts,
            "error": result.error,
            "final_answer": result.final_answer,
            "reasoning_log": state.reasoning_log(),
            "messages": state.messages,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
