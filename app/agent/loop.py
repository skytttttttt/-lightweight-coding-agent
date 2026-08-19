"""Agent Loop：核心循环（最大 30 turns，不丢 reasoning_content，含 Repair 协议）。"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path

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


class AgentLoop:
    def __init__(self, client: DeepSeekClient, registry: ToolRegistry,
                 max_turns: int = 30, max_repairs: int = 2, log_dir: Path | None = None):
        self.client = client
        self.registry = registry
        self.max_turns = max_turns
        self.max_repairs = max_repairs
        self.log_dir = log_dir or Path("logs")
        self.log_dir.mkdir(parents=True, exist_ok=True)

    # ---------- 修复状态跟踪 ----------
    @staticmethod
    def _is_failure(output: str) -> bool:
        """判断工具结果是否为失败（error / 测试失败）。"""
        return output.strip().startswith("[error]") or "exit_code=" in output and "exit_code=0" not in output

    def run(self, task: str, system_prompt: str | None = None) -> AgentResult:
        prompt = system_prompt or build_system_prompt()
        state = AgentState(prompt, task)
        result = AgentResult(task=task)
        repair_attempts = 0
        last_failed = False

        for turn_no in range(1, self.max_turns + 1):
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
                output = self.registry.execute(tc.name, tc.arguments)
                state.add_tool_result(tc.id, tc.name, output)
                turn.tool_results.append({"tool_call_id": tc.id, "name": tc.name, "output": output})
                if self._is_failure(output):
                    any_failure = True

            # Repair 协议：连续失败自动修复，同一问题最多 2 次
            if any_failure:
                if last_failed:
                    repair_attempts += 1
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
        payload = {
            "task": result.task,
            "completed": result.completed,
            "stopped_by": result.stopped_by,
            "turns_used": result.turns_used,
            "repair_attempts": result.repair_attempts,
            "final_answer": result.final_answer,
            "reasoning_log": state.reasoning_log(),
            "messages": state.messages,
        }
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
        return str(path)
