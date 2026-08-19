"""Sandbox：将所有 Agent 文件操作限制在 workspace/ 内，拒绝路径逃逸。

核心规则：
- 所有文件操作路径必须解析到 workspace/ 之下。
- 拒绝 ../../ 等路径穿越（如 ../../etc/passwd 必须被拒绝）。
- 命令执行带危险命令黑名单。
"""
from __future__ import annotations

import re
from pathlib import Path

# 危险命令前缀/关键字（精确匹配命令名）
DANGEROUS_COMMANDS = {
    "rm", "del", "format", "sudo", "shutdown", "reboot", "mkfs",
    "diskutil", "killall", "pkill", "kill", "dd", "chmod", "chown",
    "git",  # git 需要白名单之外的额外校验（reset --hard / clean -fd / push --force）
}

# git 危险子命令（git 属于"部分允许"，这些子命令禁止）
GIT_DANGEROUS_SUBCOMMANDS = {"reset", "clean", "push", "rebase", "filter-branch"}


class SandboxError(Exception):
    """沙箱拒绝访问或执行。"""


class Sandbox:
    def __init__(self, workspace: Path):
        self.workspace = Path(workspace).resolve()

    # ---------- 路径解析 ----------
    def resolve(self, path: str | Path) -> Path:
        """将任意路径解析为 workspace 内的绝对路径；逃逸则拒绝。"""
        p = Path(str(path).strip() or ".")
        # 拒绝显式 ../ 与 .. 段
        if ".." in p.parts or ".." in str(p):
            raise SandboxError(f"路径逃逸被拒绝: {path!r}（不允许使用 '..'）")
        # 处理绝对/相对路径
        if p.is_absolute():
            candidate = p
        else:
            candidate = self.workspace / p
        candidate = candidate.resolve()
        # 校验落在 workspace 内
        if not (candidate == self.workspace or self.workspace in candidate.parents):
            raise SandboxError(f"路径逃逸被拒绝: {path!r} 位于 workspace 之外")
        return candidate

    # ---------- 命令校验 ----------
    def check_command(self, command: str) -> str:
        """校验命令安全；返回清洗后的命令。危险命令抛 SandboxError。"""
        cmd = command.strip()
        if not cmd:
            raise SandboxError("空命令")
        # 提取第一个 token（命令名）
        tokens = cmd.split()
        base = tokens[0]
        name = Path(base).name.lower()

        if name in DANGEROUS_COMMANDS or any(
            name.startswith(f"{d}.") for d in DANGEROUS_COMMANDS if d != "git"
        ):
            # git 特判：仅部分子命令禁止
            if name == "git":
                if len(tokens) >= 2 and tokens[1] in GIT_DANGEROUS_SUBCOMMANDS:
                    raise SandboxError(
                        f"危险命令被拒绝: {base} {tokens[1]}（禁止破坏性 git 操作）"
                    )
                return cmd
            raise SandboxError(f"危险命令被拒绝: {base}")
        return cmd


def default_sandbox() -> Sandbox:
    from app.config import get_config

    cfg = get_config()
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    return Sandbox(cfg.workspace_dir)
