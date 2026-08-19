"""AgentLoop 测试：使用 FakeClient 模拟 tool calling 与最终答案，验证消息序列、repair 限制。"""
import tempfile
from pathlib import Path

import pytest

from app.agent.loop import AgentLoop
from app.model.client import ModelResponse, ToolCall
from app.security.sandbox import Sandbox
from app.tools.registry import build_registry


class FakeClient:
    """模拟两轮：第一轮 list_files（带 reasoning），第二轮最终答案。"""

    def __init__(self, steps):
        self.steps = steps
        self.calls = 0

    def chat(self, messages, tools=None):
        self.calls += 1
        if self.calls > len(self.steps):
            raise RuntimeError("超过模拟步数")
        step = self.steps[self.calls - 1]
        return step(messages)


def _tool_call(name, args, cid="call_1"):
    return ToolCall(id=cid, name=name, arguments=args)


@pytest.fixture
def loop(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "a.txt").write_text("hello world\n")
    sb = Sandbox(ws)
    registry = build_registry(sb)
    client = FakeClient([
        lambda m: ModelResponse(
            content=None,
            reasoning_content="先看看有哪些文件",
            tool_calls=[_tool_call("list_files", {"path": "."})],
        ),
        lambda m: ModelResponse(content="任务完成", reasoning_content="检查完毕"),
    ])
    log_dir = tmp_path / "logs"
    return AgentLoop(client, registry, max_turns=30, max_repairs=2, log_dir=log_dir)


def test_loop_completes(loop):
    result = loop.run("测试任务")
    assert result.completed is True
    assert result.final_answer == "任务完成"
    assert result.turns_used == 2
    assert "先看看有哪些文件" in result.reasoning_log


def test_loop_message_sequence(loop):
    # 验证 tool 结果已注入消息
    result = loop.run("测试任务")
    import json
    log = json.loads(Path(result.log_path).read_text(encoding="utf-8"))
    roles = [m["role"] for m in log["messages"]]
    assert "assistant" in roles and "tool" in roles
    # reasoning 已保存
    assert "检查完毕" in log["reasoning_log"]


def test_repair_limit_stops():
    """连续失败超过 2 次应停止。"""
    ws = Path("/tmp") / "loop_repair_test" if False else None
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ws = root / "workspace"
        ws.mkdir()
        sb = Sandbox(ws)
        registry = build_registry(sb)
        # 每轮都失败
        client = FakeClient([
            lambda m: ModelResponse(content=None, tool_calls=[
                _tool_call("run_command", {"command": "python -c 'raise SystemExit(1)'"}, cid=f"c{i}")
            ]) for i in range(5)
        ])
        loop = AgentLoop(client, registry, max_turns=30, max_repairs=2, log_dir=root / "logs")
        result = loop.run("会失败的测试")
        assert result.completed is False
        assert result.stopped_by == "repair_limit"
        assert result.repair_attempts >= 2


def test_max_turns_stops():
    with tempfile.TemporaryDirectory() as td:
        root = Path(td)
        ws = root / "workspace"
        ws.mkdir()
        sb = Sandbox(ws)
        registry = build_registry(sb)
        # 一直返回 tool call，且成功（不触发 repair），但轮次用尽
        client = FakeClient([
            lambda m: ModelResponse(content=None, tool_calls=[
                _tool_call("list_files", {"path": "."}, cid=f"c{i}")
            ]) for i in range(40)
        ])
        loop = AgentLoop(client, registry, max_turns=5, max_repairs=2, log_dir=root / "logs")
        result = loop.run("无限循环任务")
        assert result.stopped_by == "max_turns"
        assert result.turns_used == 5
