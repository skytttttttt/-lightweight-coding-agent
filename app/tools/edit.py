"""编辑工具：edit_file。

基于精确字符串替换实现，要求 old_text 唯一匹配，避免误改。
"""
from __future__ import annotations

from app.security.sandbox import Sandbox, SandboxError


def edit_file(sandbox: Sandbox, path: str, old_text: str, new_text: str,
              replace_all: bool = False) -> str:
    """将文件中的 old_text 替换为 new_text。"""
    try:
        target = sandbox.resolve(path)
    except SandboxError as e:
        return f"[error] {e}"
    if not target.exists():
        return f"[error] 文件不存在: {path}"
    if not target.is_file():
        return f"[error] 不是文件: {path}"
    try:
        text = target.read_text(encoding="utf-8")
    except OSError as e:
        return f"[error] 读取失败: {e}"
    if not old_text:
        return "[error] old_text 不能为空"
    count = text.count(old_text)
    if count == 0:
        return "[error] 未找到 old_text，无法替换"
    if count > 1 and not replace_all:
        return f"[error] old_text 匹配 {count} 处，请提供更精确的上下文或设置 replace_all=true"
    new = text.replace(old_text, new_text) if replace_all else text.replace(old_text, new_text, 1)
    try:
        target.write_text(new, encoding="utf-8")
    except OSError as e:
        return f"[error] 写入失败: {e}"
    return f"[ok] 已替换 {count if replace_all else 1} 处 -> {path}"
