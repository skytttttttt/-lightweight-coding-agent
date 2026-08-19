"""命令执行工具：run_command。

允许项目测试/构建命令；危险命令被 Sandbox 黑名单拒绝。
工作目录限定在项目根或 workspace 内。
"""
from __future__ import annotations

import subprocess
from pathlib import Path

from app.security.sandbox import Sandbox, SandboxError

MAX_OUTPUT_CHARS = 12000
DEFAULT_TIMEOUT = 60


def run_command(sandbox: Sandbox, command: str, workdir: str = "project", timeout: int = DEFAULT_TIMEOUT) -> str:
    """在受限工作目录内执行命令并返回输出。"""
    try:
        cleaned = sandbox.check_command(command)
    except SandboxError as e:
        return f"[error] {e}"

    project_root = sandbox.workspace.parent
    if workdir == "project":
        cwd = project_root
    else:
        try:
            cwd = sandbox.resolve(workdir)
        except SandboxError as e:
            return f"[error] {e}"

    try:
        proc = subprocess.run(
            cleaned,
            shell=True,
            cwd=str(cwd),
            capture_output=True,
            text=True,
            timeout=max(1, timeout),
        )
    except subprocess.TimeoutExpired:
        return f"[error] 命令超时（>{timeout}s）: {command}"
    except Exception as e:  # noqa: BLE001
        return f"[error] 执行失败: {e}"

    output = (proc.stdout or "") + (proc.stderr or "")
    if len(output) > MAX_OUTPUT_CHARS:
        output = output[:MAX_OUTPUT_CHARS] + "\n...(输出已截断)"
    status = "ok" if proc.returncode == 0 else "error"
    return f"[{status}] exit_code={proc.returncode} cwd={cwd}\n{output}"
