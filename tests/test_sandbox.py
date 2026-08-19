"""Sandbox 测试：路径逃逸拒绝、命令黑名单。"""
import pytest

from app.security.sandbox import Sandbox, SandboxError


@pytest.fixture
def sandbox(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    return Sandbox(ws)


def test_resolve_normal(sandbox):
    p = sandbox.resolve("a/b.txt")
    assert p.is_absolute()
    assert str(sandbox.workspace) in str(p)


def test_reject_parent_traversal(sandbox):
    for evil in ["../../etc/passwd", "a/../../etc/passwd", "..", "../.."]:
        with pytest.raises(SandboxError):
            sandbox.resolve(evil)


def test_reject_absolute_outside(sandbox):
    with pytest.raises(SandboxError):
        sandbox.resolve("/etc/passwd")


def test_reject_dangerous_commands(sandbox):
    for cmd in ["rm -rf /", "sudo reboot", "mkfs.ext4 /dev/sda", "diskutil erase disk0",
                "shutdown -h now", "git reset --hard", "git clean -fd", "git push --force"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_allow_safe_commands(sandbox):
    for cmd in ["pytest", "python -m pytest tests", "git diff", "git status", "python app/main.py"]:
        assert sandbox.check_command(cmd) == cmd
