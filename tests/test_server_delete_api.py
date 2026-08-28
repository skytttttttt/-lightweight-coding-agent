"""长按删除 API 测试：POST /api/files/delete。

覆盖：删文件 / 递归删目录 / 根目录拒绝 / 逃逸拒绝 / 敏感路径拒绝 / 不存在 / 空路径 / 控制字符 / 未加载项目。
安全语义：删除前必须经 Sandbox 校验；禁止删根、禁止删 .git/.env 等敏感路径。
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
    (project / "a.py").write_text("x = 1\n")
    sub = project / "sub"
    sub.mkdir()
    (sub / "inner.txt").write_text("hi\n")
    (sub / "nested").mkdir()
    (sub / "nested" / "deep.txt").write_text("deep\n")
    (project / ".env").write_text("SECRET=1\n")
    git = project / ".git"
    git.mkdir()
    (git / "config").write_text("[core]\n")
    server.set_active_project(name="proj", root=project)
    return TestClient(server.app)


def _delete(client, path):
    return client.post("/api/files/delete", json={"path": path})


def test_delete_file(client, tmp_path):
    """删除普通文件：成功且返回被删路径清单，物理文件确实移除。"""
    r = _delete(client, "a.py")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["path"] == "a.py"
    assert data["count"] == 1
    assert data["deleted"] == ["a.py"]
    assert not (tmp_path / "proj" / "a.py").exists()


def test_delete_directory_recursive(client, tmp_path):
    """递归删除目录：整棵子树（含子目录与文件）全部删除并完整上报。"""
    r = _delete(client, "sub")
    assert r.status_code == 200
    data = r.json()
    assert data["ok"] is True
    assert data["path"] == "sub"
    assert not (tmp_path / "proj" / "sub").exists()
    # 子级在前：deep.txt / nested / inner.txt / sub
    assert set(data["deleted"]) == {"sub", "sub/inner.txt", "sub/nested", "sub/nested/deep.txt"}
    assert data["count"] == 4


def test_delete_project_root_rejected(client):
    """禁止删除项目根目录本身。空路径 / "." → 400；绝对路径 "/" 被沙箱按逃逸拒绝（403）。"""
    for p in [".", ""]:
        r = _delete(client, p)
        assert r.status_code == 400, f"{p!r} 应被拒绝"
    r = _delete(client, "/")
    assert r.status_code == 403


def test_delete_escape_rejected(client):
    """路径逃逸（../ 穿越 / 根外绝对路径）必须被拒绝（403）。"""
    for p in ["..", "../..", "sub/../..", "/etc", "/etc/passwd", "../../../tmp/x"]:
        r = _delete(client, p)
        assert r.status_code == 403, f"{p!r} 应被拒绝"


def test_delete_sensitive_rejected(client):
    """敏感路径（.env / .git 内部）禁止删除（403），且物理文件保留。"""
    for p in [".env", ".git", ".git/config"]:
        r = _delete(client, p)
        assert r.status_code == 403, f"{p!r} 应被拒绝"


def test_delete_nonexistent_rejected(client):
    """不存在路径 → 404。"""
    r = _delete(client, "no_such_file.txt")
    assert r.status_code == 404


def test_delete_control_char_rejected(client):
    """控制字符路径 → 400。"""
    r = _delete(client, "a\x00.py")
    assert r.status_code == 400


def test_delete_without_project_rejected():
    """未加载项目 → 404。"""
    import app.server as srv
    srv._ACTIVE_PROJECT = None
    client = TestClient(server.app)
    r = _delete(client, "a.py")
    assert r.status_code == 404
