"""第二阶段整改测试：P0-1 统一 Project Root/Workspace、P0-2 reasoning_content 完整链路。

P0-2 测试验证 Model Response → AgentState → 下一轮 messages → API Request 完整链路，
不打印 API Key 与完整敏感请求体，仅做内部断言。
"""
import json

import httpx
import pytest

from app.agent.state import AgentState, Turn
from app.model.client import DeepSeekClient, ModelResponse, ToolCall
from app.security.sandbox import Sandbox, SandboxError


# ---------------- P0-1：Project Root / Workspace 统一 ----------------

@pytest.fixture
def proj_sandbox(tmp_path):
    root = tmp_path / "project"
    root.mkdir()
    (root / "README.md").write_text("# demo\n")
    (root / "app").mkdir()
    (root / "app" / "main.py").write_text("print('hi')\n")
    (root / "workspace").mkdir()
    (root / "workspace" / "note.txt").write_text("tmp\n")
    (root / ".env").write_text("DEEPSEEK_API_KEY=should_not_leak\n")
    (root / ".git").mkdir()
    (root / ".git" / "config").write_text("x\n")
    return Sandbox(root / "workspace", project_root=root)


def test_p01_resolve_within_project_root(proj_sandbox):
    # 文件工具现在能访问 Project Root 内的代码（同一根）
    p = proj_sandbox.resolve("app/main.py")
    assert "project" in str(p) and p.name == "main.py"


def test_p01_resolve_relative_to_root(proj_sandbox):
    # "README.md" 应解析到项目根，而非 workspace 内
    p = proj_sandbox.resolve("README.md")
    assert p.name == "README.md"
    assert "workspace" not in str(p)


def test_p01_reject_outside_root(proj_sandbox):
    for evil in ["../../etc/passwd", "a/../../etc/passwd", "/etc/passwd", ".."]:
        with pytest.raises(SandboxError):
            proj_sandbox.resolve(evil)


def test_p01_reject_sensitive_paths(proj_sandbox):
    # .env / .git 等敏感路径禁止访问
    for p in [".env", ".git/config", ".git", "app/../.env"]:
        with pytest.raises(SandboxError):
            proj_sandbox.resolve(p)


def test_p01_workspace_still_usable(proj_sandbox):
    # workspace 临时文件区仍可正常读写
    p = proj_sandbox.resolve("workspace/note.txt")
    assert p.read_text() == "tmp\n"


# ---------------- P0-2：reasoning_content 完整链路 ----------------

def test_p02_state_persists_reasoning():
    """AgentState：assistant 消息必须携带 reasoning_content 供下一轮发送。"""
    state = AgentState("system", "task")
    turn = Turn(
        assistant_content=None,
        reasoning_content="先分析需求",
        tool_calls=[{"id": "c1", "name": "list_files", "arguments": '{"path": "."}'}],
    )
    state.add_assistant(turn)
    asst = state.messages[-1]
    assert asst["role"] == "assistant"
    assert asst["reasoning_content"] == "先分析需求"
    assert asst["tool_calls"][0]["function"]["name"] == "list_files"


def test_p02_full_link_via_api_request():
    """完整链路：Model Response → AgentState → 下一轮 messages → API Request。

    使用 MockTransport 捕获第二轮真实发给 DeepSeek 的请求体，
    断言其中保留第一轮的 reasoning_content 与 tool 结果；不打印完整请求。
    """
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        if captured.get("first_done"):
            # 第二轮请求：验证 messages 中保留上一轮 reasoning 与 tool 结果
            msgs = body["messages"]
            asst = [m for m in msgs if m["role"] == "assistant"][-1]
            assert asst.get("reasoning_content") == "第一轮推理内容"
            assert "tool_calls" in asst
            tool_msgs = [m for m in msgs if m["role"] == "tool"]
            assert len(tool_msgs) == 1
            assert tool_msgs[0]["tool_call_id"] == "c1"
            return httpx.Response(200, json={
                "choices": [{"message": {"content": "完成", "reasoning_content": "第二轮推理",
                                          "tool_calls": None}, "finish_reason": "stop"}]
            })
        # 第一轮请求
        captured["first_done"] = True
        return httpx.Response(200, json={
            "choices": [{
                "message": {
                    "content": None,
                    "reasoning_content": "第一轮推理内容",
                    "tool_calls": [{
                        "id": "c1", "type": "function",
                        "function": {"name": "list_files", "arguments": '{"path": "."}'},
                    }],
                },
                "finish_reason": "tool_calls",
            }]
        })

    client = DeepSeekClient(api_key="test-key", base_url="https://api.deepseek.com",
                            model="deepseek-v4-flash")
    client._client = httpx.Client(transport=httpx.MockTransport(handler))

    # 第一轮：模型返回 reasoning + tool_call
    state = AgentState("sys", "任务")
    resp1 = client.chat(state.messages, tools=[{"type": "function"}])
    assert resp1.reasoning_content == "第一轮推理内容"
    turn1 = Turn(
        assistant_content=resp1.content,
        reasoning_content=resp1.reasoning_content,
        finish_reason=resp1.finish_reason,
        tool_calls=[{"id": tc.id, "name": tc.name, "arguments": json.dumps(tc.arguments)}
                    for tc in resp1.tool_calls],
    )
    state.add_assistant(turn1)
    state.add_tool_result("c1", "list_files", "[ok] files: a.py")

    # 第二轮：将完整 messages 发给 API，链路中被 handler 断言
    resp2 = client.chat(state.messages, tools=[{"type": "function"}])
    assert resp2.content == "完成"
    client.close()
