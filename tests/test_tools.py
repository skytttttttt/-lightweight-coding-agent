"""Tools 测试：list_files / read_file / search_code / edit_file / run_command / git_diff。"""
import pytest

from app.security.sandbox import Sandbox
from app.tools.command import run_command
from app.tools.edit import edit_file
from app.tools.files import list_files, read_file, write_file
from app.tools.git import git_diff
from app.tools.search import search_code


@pytest.fixture
def env(tmp_path):
    """构造 workspace 与一个 Git 项目（workspace 的父目录）。"""
    project = tmp_path / "proj"
    project.mkdir()
    ws = project / "workspace"
    ws.mkdir()
    (project / ".git").mkdir()  # 预创建，run_command 用
    return project, Sandbox(ws)


def test_list_and_read(env):
    project, sb = env
    (project / "workspace" / "hello.py").write_text("def greet():\n    return 'hi'\n")
    listing = list_files(sb, ".")
    assert "hello.py" in listing
    content = read_file(sb, "hello.py")
    assert "def greet()" in content


def test_read_reject_escape(env):
    _, sb = env
    assert read_file(sb, "../../etc/passwd").startswith("[error]")


def test_search_code(env):
    project, sb = env
    (project / "workspace" / "a.py").write_text("total = 1\nprint(total)\n")
    (project / "workspace" / "b.py").write_text("print('nope')\n")
    out = search_code(sb, "total")
    assert "a.py:1" in out
    assert "b.py" not in out


def test_edit_file(env):
    project, sb = env
    f = project / "workspace" / "x.py"
    f.write_text("alpha\nbeta\nother\n")
    r = edit_file(sb, "x.py", "alpha", "gamma")
    assert r.startswith("[ok]")
    assert f.read_text() == "gamma\nbeta\nother\n"


def test_write_file(env):
    project, sb = env
    r = write_file(sb, "sub/new.py", "x = 1\n")
    assert r.startswith("[ok]")
    assert (project / "workspace" / "sub" / "new.py").read_text() == "x = 1\n"
    r2 = write_file(sb, "../../escape.py", "x")
    assert r2.startswith("[error]")
    assert not (project / "escape.py").exists()


def test_edit_ambiguous_rejected(env):
    project, sb = env
    f = project / "workspace" / "x.py"
    f.write_text("alpha\nalpha\n")
    r = edit_file(sb, "x.py", "alpha", "gamma")
    assert r.startswith("[error]")


def test_run_command_safe(env):
    project, sb = env
    out = run_command(sb, "echo hello")
    assert "[ok]" in out and "hello" in out


def test_run_command_blocked(env):
    project, sb = env
    out = run_command(sb, "rm -rf /")
    assert out.startswith("[error]")


def test_git_diff(env):
    project, sb = env
    # 初始化真实 git 仓库
    import subprocess
    subprocess.run(["git", "init", "-q"], cwd=str(project), check=True)
    subprocess.run(["git", "config", "user.email", "t@t"], cwd=str(project))
    subprocess.run(["git", "config", "user.name", "t"], cwd=str(project))
    (project / "workspace" / "f.py").write_text("print(1)\n")
    subprocess.run(["git", "add", "."], cwd=str(project), check=True)
    subprocess.run(["git", "commit", "-q", "-m", "init"], cwd=str(project), check=True)
    (project / "workspace" / "f.py").write_text("print(2)\n")
    out = git_diff(sb)
    assert "+print(2)" in out or "-print(1)" in out
