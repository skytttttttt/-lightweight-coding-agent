"""Git 工具：git_diff / git_status。

只读操作，用于检查修改是否合规。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.security.sandbox import Sandbox

MAX_DIFF_CHARS = 12000


def _git(sandbox: Sandbox, args: list[str], timeout: int = 30) -> str:
    cwd = sandbox.root  # 统一 Project Root
    try:
        proc = subprocess.run(["git"] + args, cwd=str(cwd), capture_output=True,
                              text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return f"[error] git 命令超时: {' '.join(args)}"
    except Exception as e:  # noqa: BLE001
        return f"[error] git 执行失败: {e}"
    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > MAX_DIFF_CHARS:
        output = output[:MAX_DIFF_CHARS] + "\n...(输出已截断)"
    status = "ok" if proc.returncode == 0 else "error"
    return f"[{status}] exit_code={proc.returncode}\n{output}"


def git_diff(sandbox: Sandbox, path: str = "") -> str:
    """查看工作区改动。

    path 必须是 Project Root 内的相对路径；'..' 穿越 / Root 外绝对路径 / 敏感路径
    在进入 git subprocess 之前由 Sandbox.resolve 拒绝。
    """
    if path:
        try:
            resolved = sandbox.resolve(path)
            path = str(resolved.relative_to(sandbox.root))
        except Exception as e:  # noqa: BLE001
            return f"[error] {e}"
    args = ["diff"] + ([path] if path else [])
    return _git(sandbox, args)


def git_status(sandbox: Sandbox) -> str:
    """查看仓库状态。"""
    return _git(sandbox, ["status", "--short"])
