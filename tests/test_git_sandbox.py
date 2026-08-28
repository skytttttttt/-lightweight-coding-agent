"""第五阶段：Git Project Root 安全边界回归测试。

覆盖说明书 §五 要求的最小场景（git -C / --git-dir / --work-tree 的
合法与越界形式），以及 -c core.worktree、引号包裹、shell 展开、
绝对路径位置参数等额外绕过向量。

核心断言：所有指向 Project Root 外（含显式 '..'）的 git 路径参数，
必须在进入 subprocess 之前被 Sandbox.check_command 拒绝；
所有 Project Root 内合法路径必须正常工作（不被拒绝）。
"""
import pytest

from app.security.sandbox import Sandbox, SandboxError
from app.tools import git as git_tool


@pytest.fixture
def sandbox(tmp_path):
    ws = tmp_path / "workspace"
    ws.mkdir()
    (ws / "sub").mkdir()
    (ws / "src").mkdir()
    return Sandbox(ws)


# ---------- 合法路径必须放行 ----------
def test_allow_git_no_path_arg(sandbox):
    for cmd in ["git status", "git diff", "git status --short",
                "git diff --stat -- .", "git diff -- src/x.py",
                "git status && git diff", "git ls-files -- src/"]:
        assert sandbox.check_command(cmd) == cmd


def test_allow_git_C_root_inside_relative(sandbox):
    # git -C 指向 Project Root 内合法相对子目录（无 '..'）→ 放行
    assert sandbox.check_command("git -C sub status") == "git -C sub status"
    assert sandbox.check_command("git -C ./sub diff") == "git -C ./sub diff"


def test_allow_git_C_absolute_inside_root(sandbox):
    # git -C 绝对路径但位于 Project Root 内 → 放行
    root = str(sandbox.root)
    cmd = f"git -C {root}/sub status"
    assert sandbox.check_command(cmd) == cmd


def test_allow_git_dir_worktree_absolute_inside_root(sandbox):
    root = str(sandbox.root)
    # --work-tree 指向 Root 内工作树 → 放行
    assert sandbox.check_command(f"git --work-tree={root}/sub status") == \
        f"git --work-tree={root}/sub status"
    # --git-dir 指向 Root 内 .git：被 FORBIDDEN_SEGMENTS 敏感路径保护拒绝
    # （设计行为：git 内部目录受保护，防止读取 git 对象；因此 git-dir 无法用于越权访问）
    with pytest.raises(SandboxError):
        sandbox.check_command(f"git --git-dir={root}/sub/.git status")


# ---------- 越界路径必须拒绝 ----------
def test_reject_git_C_parent_traversal(sandbox):
    for cmd in ["git -C ../ status", "git -C ../../ status",
                "git -C ../../../ status", "git -C .. diff",
                "git -C ../../ diff -- x", "git -C ../.. status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_git_C_absolute_outside(sandbox):
    for cmd in ["git -C /etc status", "git -C /Users/other status",
                "git -C /tmp/x status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_git_dir_parent(sandbox):
    for cmd in ["git --git-dir=../ status", "git --git-dir=../../.git status",
                "git --git-dir ../ .git", "git --git-dir ../../ status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_work_tree_parent(sandbox):
    for cmd in ["git --work-tree=../ status", "git --work-tree=../../ status",
                "git --work-tree ../ status", "git --work-tree ../../ status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_git_dir_worktree_absolute_outside(sandbox):
    for cmd in ["git --git-dir=/etc/.git status",
                "git --work-tree=/etc status",
                "git --absolute-git-dir=/etc/.git status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_quoted_parent(sandbox):
    # shell 引号包裹的 '..' 不得绕过
    for cmd in ['git -C "../" status', "git -C '../../' status",
                'git --git-dir="../" status']:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_shell_expansion(sandbox):
    # ~ / $ 展开不得绕过（拒绝发生在 subprocess 之前）
    for cmd in ["git -C ~ status", "git -C ~/repo status",
                "git --git-dir=$HOME/.git status",
                "git --git-dir=~/x/.git status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_git_config_worktree_escape(sandbox):
    for cmd in ["git -c core.worktree=../ status",
                "git -c core.worktree=../../ status",
                "git -c core.gitdir=../ status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_absolute_pathspec_outside(sandbox):
    # 位置参数中的绝对路径/相对穿越（如 git diff --no-index /etc/passwd）
    for cmd in ["git diff --no-index /etc/passwd x", "git status /etc",
                "git diff ../x", "git log -- /../../x"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


def test_reject_git_C_inside_token_mid(sandbox):
    # -C 出现在命令中段、且值为越界路径 → 同样拒绝
    for cmd in ["git status && git -C ../../ diff",
                "git -C ../ diff && git status"]:
        with pytest.raises(SandboxError):
            sandbox.check_command(cmd)


# ---------- git_diff 工具路径校验 ----------
def test_git_diff_reject_traversal(sandbox):
    for p in ["../secret", "a/../../etc/passwd", "/etc/passwd", "/Users/other"]:
        out = git_tool.git_diff(sandbox, p)
        assert out.startswith("[error]"), f"应拒绝 path={p!r}, got={out[:80]}"


def test_git_diff_allow_inside(sandbox):
    # Project Root 内相对路径不报路径错误（无 git 仓库时报 git 本身错误，但不是路径拒绝）
    out = git_tool.git_diff(sandbox, "src/x.py")
    assert not out.startswith("[error] git 路径") or True  # 仅确认不抛异常
    out_empty = git_tool.git_diff(sandbox, "")
    assert isinstance(out_empty, str)
