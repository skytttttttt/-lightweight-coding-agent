"""Web Project Explorer 文件树 API 测试：读取根 / 目录层级 / 空目录 / 逃逸拒绝 / 敏感文件保护。

P0 语义：/api/files 只在「存在激活项目」时返回真实文件树；未激活时返回 active=False 空态。
因此本文件用 set_active_project 建立激活项目根，与真实上传后路径一致。
"""
import pytest
from starlette.testclient import TestClient

import app.server as server


@pytest.fixture(autouse=True)
def reset_active(monkeypatch):
    """每个用例前清空激活项目，避免跨用例残留。"""
    monkeypatch.setattr(server, "_ACTIVE_PROJECT", None)


@pytest.fixture
def client(tmp_path, reset_active):
    """用临时 Project Root 建立激活项目，隔离真实项目文件系统。"""
    project = tmp_path / "proj"
    project.mkdir()
    ws = project / "workspace"
    ws.mkdir()
    (project / "a.py").write_text("x = 1\n")
    sub = project / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("hi\n")
    (sub / "empty").mkdir()
    (project / ".env").write_text("SECRET=1\n")
    (project / ".env.example").write_text("SECRET=\n")
    (project / ".env.local").write_text("X=1\n")
    git = project / ".git"
    git.mkdir()
    (git / "config").write_text("[core]\n")
    server.set_active_project(name="proj", root=project)
    return TestClient(server.app)


def test_no_project_returns_empty_state(client):
    """初始无激活项目：/api/files 必须返回空态（active=False, tree=None），禁止预设/Demo 文件。"""
    # 清空激活状态模拟「未加载项目」
    import app.server as srv
    srv._ACTIVE_PROJECT = None
    r = client.get("/api/files", params={"path": "."})
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is False
    assert data["tree"] is None


def test_read_project_root(client):
    """Web 可读取当前 Project Root（路径 '.' 解析到根，返回目录树一层）。"""
    r = client.get("/api/files", params={"path": "."})
    assert r.status_code == 200
    data = r.json()
    assert data["active"] is True
    assert data["tree"]["type"] == "directory"
    assert data["root_name"] == "proj"
    names = {ch["name"] for ch in data["tree"]["children"]}
    assert {"a.py", "sub", "workspace"} <= names


def test_directory_levels(client):
    """支持目录层级：子目录可继续按相对路径展开。"""
    r = client.get("/api/files", params={"path": "sub"})
    assert r.status_code == 200
    names = {ch["name"] for ch in r.json()["tree"]["children"]}
    assert "inner.txt" in names
    assert "empty" in names


def test_empty_directory_has_empty_children(client):
    """空目录：正常返回且 children 为空列表（供前端渲染'空目录'提示/懒加载）。"""
    r = client.get("/api/files", params={"path": "sub/empty"})
    assert r.status_code == 200
    tree = r.json()["tree"]
    assert tree["type"] == "directory"
    assert tree["children"] == []


def test_sensitive_files_hidden_from_tree(client):
    """.env 及 .env* 变体、.git 等敏感目录不进入文件树。"""
    r = client.get("/api/files", params={"path": "."})
    names = {ch["name"] for ch in r.json()["tree"]["children"]}
    assert ".env" not in names
    assert ".env.example" not in names
    assert ".env.local" not in names
    assert ".git" not in names


def test_escape_paths_rejected(client):
    """路径逃逸（.. 穿越 / 根外绝对路径）必须被拒绝（403）。"""
    for p in ["..", "../..", "sub/../..", "/etc", "/etc/passwd"]:
        r = client.get("/api/files", params={"path": p})
        assert r.status_code == 403, f"{p!r} 应被拒绝"


def test_sensitive_path_access_rejected(client):
    """通过文件树直接访问 .env 必须被拒绝。"""
    r = client.get("/api/files", params={"path": ".env"})
    assert r.status_code == 403
