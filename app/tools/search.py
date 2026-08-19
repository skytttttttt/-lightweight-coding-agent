"""搜索工具：search_code。

不依赖系统 rg，使用纯 Python 实现递归搜索，保证可移植性。
"""
from __future__ import annotations

import fnmatch
import os
from pathlib import Path

from app.security.sandbox import Sandbox, SandboxError

# 默认跳过的目录
SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "logs", ".pytest_cache"}

DEFAULT_PATTERNS = ["*.py", "*.md", "*.txt", "*.json", "*.yaml", "*.yml", "*.toml",
                    "*.ini", "*.cfg", "*.sh", "*.html", "*.css", "*.js", "*.ts"]


def _matches(patterns: list[str] | None, name: str) -> bool:
    if not patterns:
        return True
    return any(fnmatch.fnmatch(name, p) for p in patterns)


def search_code(sandbox: Sandbox, query: str, path: str = ".", file_patterns: list[str] | None = None,
                case_sensitive: bool = False, max_results: int = 100) -> str:
    """在 workspace 内递归搜索包含 query 的代码行。"""
    try:
        root = sandbox.resolve(path)
    except SandboxError as e:
        return f"[error] {e}"
    if not root.exists():
        return f"[error] 路径不存在: {path}"
    if not root.is_dir():
        return f"[error] 不是目录: {path}"

    pats = file_patterns or DEFAULT_PATTERNS
    needle = query if case_sensitive else query.lower()
    results = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS]
        for fname in filenames:
            if not _matches(pats, fname):
                continue
            fpath = Path(dirpath) / fname
            try:
                rel = fpath.relative_to(sandbox.workspace)
                with open(fpath, "r", encoding="utf-8", errors="replace") as fh:
                    for lineno, line in enumerate(fh, start=1):
                        check = line if case_sensitive else line.lower()
                        if needle in check:
                            results.append(f"{rel}:{lineno}: {line.rstrip()}")
                            if len(results) >= max_results:
                                break
            except OSError:
                continue
            if len(results) >= max_results:
                break
        if len(results) >= max_results:
            break
    if not results:
        return f"(未找到包含 {query!r} 的代码)"
    return "\n".join(results)
