"""Sandbox：将 Agent 文件/命令操作统一限定在 Project Root 内，拒绝根外部访问。

核心规则：
- 所有文件操作路径必须解析到 Project Root 之下（File/Search/Edit/Write/Command/Git 统一针对同一根）。
- 拒绝 ../../ 等路径穿越与任何落在 Project Root 之外的绝对路径。
- 保护敏感文件（.env / .git 内部），防止 Agent 读取并泄露密钥。
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

# 根内禁止文件工具访问的敏感路径片段（防止密钥泄露）
FORBIDDEN_SEGMENTS = {".git", ".env", ".ssh", ".aws", ".kube"}


class SandboxError(Exception):
    """沙箱拒绝访问或执行。"""


class Sandbox:
    def __init__(self, workspace: Path, project_root: Path | None = None):
        """workspace：工作区根；project_root：统一文件操作根（默认等于 workspace，兼容旧用法）。"""
        self.workspace = Path(workspace).resolve()
        self.root = Path(project_root).resolve() if project_root else self.workspace

    # ---------- 路径解析 ----------
    def resolve(self, path: str | Path) -> Path:
        """将任意路径解析为 Project Root 内的绝对路径；逃逸或敏感路径则拒绝。"""
        p = Path(str(path).strip() or ".")
        # 拒绝显式 ../ 与 .. 段
        if ".." in p.parts or ".." in str(p):
            raise SandboxError(f"路径逃逸被拒绝: {path!r}（不允许使用 '..'）")
        # 处理绝对/相对路径
        if p.is_absolute():
            candidate = p
        else:
            candidate = self.root / p
        candidate = candidate.resolve()
        # 校验落在 Project Root 内
        if not (candidate == self.root or self.root in candidate.parents):
            raise SandboxError(f"路径逃逸被拒绝: {path!r} 位于 Project Root 之外")
        # 保护敏感路径（.git / .env 等），防止密钥泄露
        rel = candidate.relative_to(self.root)
        for seg in rel.parts:
            if seg in FORBIDDEN_SEGMENTS:
                raise SandboxError(f"敏感路径被拒绝: {path!r}（禁止访问 {seg}）")
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
            # git 特判：危险子命令 + Git 路径参数（-C / --git-dir / --work-tree 等）必须
            # 在进入 subprocess 之前完成 Project Root 边界校验，禁止参数级路径绕过
            if name == "git":
                if len(tokens) >= 2 and tokens[1] in GIT_DANGEROUS_SUBCOMMANDS:
                    raise SandboxError(
                        f"危险命令被拒绝: {base} {tokens[1]}（禁止破坏性 git 操作）"
                    )
                self._validate_git_args(tokens)
                return cmd
            raise SandboxError(f"危险命令被拒绝: {base}")
        return cmd

    # ---------- Git 路径参数校验 ----------
    # git 中可携带"仓库/工作树/工作目录"路径语义的参数（-= 前缀；<value> 取等号后或下一 token）
    _GIT_PATH_OPTIONS = {
        "-C", "--directory",            # 切换 git 工作目录（支持相对/绝对路径）
        "--git-dir", "--absolute-git-dir",  # 指定 .git 目录
        "--work-tree",                  # 指定工作树
    }
    # `-c key=value` 中携带路径语义的配置键（core.worktree / core.gitdir 等）
    _GIT_CONFIG_PATH_KEYS = ("core.worktree", "core.gitdir")

    def _validate_git_path(self, value: str, where: str) -> None:
        """校验单个 git 路径参数值：禁止 '..' 穿越、shell 展开与 Project Root 外绝对路径。"""
        v = value.strip().strip('"').strip("'")
        if not v or v == "=":
            return
        if v.startswith("~") or "$" in v:
            raise SandboxError(
                f"git 路径参数被拒绝: {value!r}（{where} 不允许 shell 展开/变量）"
            )
        # 拒绝显式 '..' 路径穿越（无论最终是否落在 Root 内，显式 .. 一律视为越界尝试）
        if ".." in v.split("/") or "\\.." in v or "..\\" in v:
            raise SandboxError(
                f"git 路径参数被拒绝: {value!r}（{where} 不允许 '..' 路径穿越）"
            )
        # 绝对路径必须解析后位于 Project Root 内（复用 resolve 的敏感段保护）
        if v.startswith("/"):
            try:
                self.resolve(v)
            except SandboxError as e:
                raise SandboxError(
                    f"git 路径参数被拒绝: {value!r}（{where} {e}）"
                )

    def _validate_git_args(self, tokens: list[str]) -> None:
        """校验 git 命令的全部参数级路径语义（-C / --git-dir / --work-tree / -c 配置）。

        目标：Git 路径参数绕过 Project Root 的通用问题，不针对单一 Case。
        拒绝必须发生在进入 git subprocess 之前（本方法在 check_command 内调用）。
        """
        i = 1
        n = len(tokens)
        while i < n:
            tok = tokens[i]
            # 选项（以 - 开头）
            if tok.startswith("-") and tok != "--":
                if tok == "-c":
                    # -c key=value：仅校验含路径语义的配置键
                    if i + 1 < n and "=" in tokens[i + 1]:
                        key, _, val = tokens[i + 1].partition("=")
                        if any(k in key.lower() for k in ("worktree", "gitdir", ".dir")):
                            self._validate_git_path(val, f"-c {key}")
                    i += 2
                    continue
                # 形如 --opt=value
                if "=" in tok:
                    key, _, val = tok.partition("=")
                    if key in self._GIT_PATH_OPTIONS:
                        self._validate_git_path(val, key)
                    i += 1
                    continue
                # 形如 -C value / --git-dir value / --work-tree value
                if tok in self._GIT_PATH_OPTIONS:
                    if i + 1 < n:
                        self._validate_git_path(tokens[i + 1], tok)
                    i += 2
                    continue
                # 其余选项不携带路径语义，跳过
                i += 1
                continue
            # 位置参数：子命令名/路径。仅当含 '..' 或为绝对路径时才做边界校验，
            # 其余（src/x.py、. 等合法相对路径）保持可用
            if tok == "--":
                i += 1
                continue
            if ".." in tok.split("/") or tok.startswith("/"):
                self._validate_git_path(tok, "路径参数")
            i += 1


def default_sandbox() -> Sandbox:
    from app.config import get_config

    cfg = get_config()
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    # 统一根 = Project Root；workspace 作为临时/测试文件建议目录
    return Sandbox(cfg.workspace_dir, project_root=cfg.project_root)
