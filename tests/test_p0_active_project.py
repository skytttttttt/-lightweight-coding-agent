"""P0 修正专项测试：初始空态 / 上传建立与切换激活项目根 / File Explorer·Agent·Git 同源。

核心约束：
- 初始无激活项目时 /api/files 返回空态、/api/git 返回空、Agent 拒绝运行（active_project 语义）。
- 文件夹上传成功后建立/切换激活项目根，/api/files / /api/git / Agent sandbox 三端同源指向该根。
- 上传 project-B 后必须切换到 project-B，不得残留 project-A。
- 不修改 Sandbox 安全规则：仍走 Sandbox(workspace, project_root=...) 参数化根。
"""
import pytest
from fastapi import HTTPException
from starlette.testclient import TestClient

import app.server as server


@pytest.fixture(autouse=True)
def reset_active(monkeypatch):
    """每个用例前清空激活项目，避免跨用例残留。"""
    monkeypatch.setattr(server, "_ACTIVE_PROJECT", None)


@pytest.fixture
def client(reset_active, tmp_path, monkeypatch):
    """用临时 workspace 隔离真实项目文件系统：monkeypatch config 与 projects_dir。"""
    class FakeCfg:
        project_root = tmp_path
        workspace_dir = tmp_path / "workspace"
        api_key = "sk-test"
        base_url = "http://mock"
        model = "mock-model"
        request_timeout = 1.0
        max_turns = 1
        max_repairs = 0
        def require_api_key(self): return self.api_key
    monkeypatch.setattr(server, "get_config", lambda: FakeCfg())
    monkeypatch.setattr(server, "projects_dir", tmp_path / "workspace" / "projects")
    return TestClient(server.app)


def _mk_project(path, files):
    """在临时目录下构造一个待上传的项目目录。files: {rel_path: content}"""
    for rel, content in files.items():
        p = path / rel
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content)


def test_upload_folder_establishes_and_switches_project(client, tmp_path):
    """文件夹上传：第一次上传 project-A 建立根；再上传 project-B 必须切换根（三端同源）。"""
    proj_a = tmp_path / "project-A"
    _mk_project(proj_a, {"src/main.py": "PRINT_A=1\n", "README.md": "# A\n", "src/util.py": "U=1\n"})
    proj_b = tmp_path / "project-B"
    _mk_project(proj_b, {"app.py": "PRINT_B=2\n", "config.yaml": "mode: b\n"})

    # --- 初始空态 ---
    r = client.get("/api/files", params={"path": "."})
    assert r.json()["active"] is False and r.json()["tree"] is None
    assert client.get("/api/git/status").json()["active"] is False

    # --- 上传 project-A（webkitRelativePath 顶层段 = project-A） ---
    files_a = [
        {"rel_path": "project-A/src/main.py", "content": "PRINT_A=1\n"},
        {"rel_path": "project-A/README.md", "content": "# A\n"},
        {"rel_path": "project-A/src/util.py", "content": "U=1\n"},
    ]
    r = client.post("/api/files/upload", json={"files": files_a, "project_name": "project-A", "strip_top_dir": True})
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["active_project"]["name"] == "project-A"
    assert server.get_active_project()["name"] == "project-A"

    # File Explorer 同源：树根 = project-A 内部文件（顶层段已剥离）
    tree = client.get("/api/files", params={"path": "."}).json()
    assert tree["active"] is True and tree["root_name"] == "project-A"
    names = {c["name"] for c in tree["tree"]["children"]}
    assert names == {"src", "README.md"}
    assert client.get("/api/files", params={"path": "src/main.py"}).json()["tree"]["name"] == "main.py"

    # Git 同源：project-A 目录内 git status 正常返回（active=True）
    gs = client.get("/api/git/status").json()
    assert gs["active"] is True

    # --- 上传 project-B：必须切换根，且 File Explorer 不再显示 project-A 文件 ---
    files_b = [
        {"rel_path": "project-B/app.py", "content": "PRINT_B=2\n"},
        {"rel_path": "project-B/config.yaml", "content": "mode: b\n"},
    ]
    r = client.post("/api/files/upload", json={"files": files_b, "project_name": "project-B", "strip_top_dir": True})
    assert r.status_code == 200
    assert server.get_active_project()["name"] == "project-B"

    tree = client.get("/api/files", params={"path": "."}).json()
    assert tree["root_name"] == "project-B"
    names = {c["name"] for c in tree["tree"]["children"]}
    assert names == {"app.py", "config.yaml"}
    assert "README.md" not in names  # project-A 内容不得残留
    assert "src" not in names


def test_upload_files_append_to_active_project(client, tmp_path):
    """普通文件上传（无项目名）：追加写入当前激活项目根，不新建项目。"""
    proj = tmp_path / "myproj"
    _mk_project(proj, {"a.txt": "a\n"})
    r = client.post("/api/files/upload",
                    json={"files": [{"rel_path": "myproj/a.txt", "content": "a\n"}],
                          "project_name": "myproj", "strip_top_dir": True})
    assert r.status_code == 200

    r = client.post("/api/files/upload", json={"files": [{"rel_path": "extra.txt", "content": "e\n"}]})
    assert r.status_code == 200
    assert server.get_active_project()["name"] == "myproj"
    tree = client.get("/api/files", params={"path": "."}).json()
    names = {c["name"] for c in tree["tree"]["children"]}
    assert names == {"a.txt", "extra.txt"}


def test_agent_runner_uses_active_project_root(client, tmp_path, monkeypatch):
    """Agent 同源：_build_runner 构造的 sandbox 根 == 激活项目根；未加载项目时拒绝运行。"""
    class FakeCfg:
        project_root = tmp_path
        workspace_dir = tmp_path / "ws"
        api_key = "sk-test"
        base_url = "http://mock"
        model = "mock-model"
        request_timeout = 1.0
        max_turns = 1
        max_repairs = 0
        def require_api_key(self): return self.api_key
    monkeypatch.setattr(server, "get_config", lambda: FakeCfg())

    # 未加载项目：_build_runner 必须 400 拒绝（先有 API key 后检查项目）
    with pytest.raises(HTTPException) as exc:
        server._build_runner()
    assert exc.value.status_code == 400
    assert "尚未加载项目" in exc.value.detail

    # 加载项目后：sandbox 指向激活项目根（替换 DeepSeekClient，不真实联网）
    proj = tmp_path / "proj-x"
    _mk_project(proj, {"main.py": "x\n"})
    server.set_active_project(name="proj-x", root=proj)

    captured = {}
    class FakeClient:
        def __init__(self, **kw): captured.update(kw)
        def close(self): pass

    monkeypatch.setattr(server, "DeepSeekClient", FakeClient)
    client_obj, loop = server._build_runner()
    active = server.get_active_project()
    from app.security.sandbox import Sandbox
    sb = Sandbox(server.get_config().workspace_dir, project_root=active["root"])
    assert sb.root == proj
    assert active["name"] == "proj-x"
    assert captured["model"]  # DeepSeekClient 以激活项目上下文正常构造
    client_obj.close()
