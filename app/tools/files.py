"""文件类工具：list_files / read_file。

所有路径必须经过 Sandbox 解析，限制在 workspace/ 内。
"""
from __future__ import annotations

from pathlib import Path

from app.security.sandbox import Sandbox, SandboxError

MAX_READ_BYTES = 512 * 1024  # 512KB


def list_files(sandbox: Sandbox, path: str = ".") -> str:
    """列出目录内容（不递归）。"""
    try:
        target = sandbox.resolve(path)
    except SandboxError as e:
        return f"[error] {e}"
    if not target.exists():
        return f"[error] 路径不存在: {path}"
    if not target.is_dir():
        return f"[error] 不是目录: {path}"
    lines = []
    for entry in sorted(target.iterdir()):
        suffix = "/" if entry.is_dir() else ""
        lines.append(f"{entry.name}{suffix}")
    return "\n".join(lines) if lines else "(空目录)"


def read_file(sandbox: Sandbox, path: str, offset: int = 0, limit: int = 200) -> str:
    """读取文本文件，支持 offset/limit 分页。"""
    try:
        target = sandbox.resolve(path)
    except SandboxError as e:
        return f"[error] {e}"
    if not target.exists():
        return f"[error] 文件不存在: {path}"
    if not target.is_file():
        return f"[error] 不是文件: {path}"
    try:
        data = target.read_bytes()
    except OSError as e:
        return f"[error] 读取失败: {e}"
    if len(data) > MAX_READ_BYTES:
        return f"[error] 文件过大({len(data)} bytes)，超过上限 {MAX_READ_BYTES}"
    text = data.decode("utf-8", errors="replace")
    lines = text.splitlines()
    start = max(offset, 0)
    end = start + limit if limit > 0 else len(lines)
    chunk = lines[start:end]
    total = len(lines)
    body = "\n".join(f"{start + i + 1:>6} | {ln}" for i, ln in enumerate(chunk))
    more = f"\n... (共 {total} 行，已显示 {start + 1}-{end} 行，可继续用 offset={end})" if end < total else ""
    return body + more
