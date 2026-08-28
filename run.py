#!/usr/bin/env python3
"""V4-Flash Coding Agent —— 本地启动器（Open Source 入口）。

用法：
    python run.py                       # 默认 127.0.0.1:8000
    HOST=127.0.0.1 PORT=8801 python run.py   # 自定义地址/端口
    PORT=0 python run.py                # 自动选择空闲端口并打印实际 URL

安全边界：
    - 默认只监听 127.0.0.1（本机回环），绝不默认暴露到局域网。
    - 除非显式设置 HOST=0.0.0.0，否则同一网络中的其他设备无法访问本 Agent API。
    - 默认端口被占用时会给出明确错误，不会静默换端口。

启动时会执行 Environment Check（Python / Git / Model API / Workspace 可写性），
任一可选组件缺失只给出警告、不阻断启动（对应 UI 显示优雅降级状态）。
"""
from __future__ import annotations

import socket
import subprocess
import sys
from pathlib import Path

# 保证从任意工作目录启动都能 import 到 app 包
sys.path.insert(0, str(Path(__file__).resolve().parent))

import shutil  # noqa: E402

from app.config import get_config  # noqa: E402

BANNER = "V4-Flash Coding Agent"


def _check_python() -> None:
    bits = 64 if sys.maxsize > 2**32 else 32
    print(f"[env] Python {sys.version.split()[0]} ({bits}-bit)")


def _check_git(warnings: list[str]) -> None:
    git = shutil.which("git")
    if not git:
        warnings.append(
            "Git: Not installed —— 非 Git 项目仍可使用 File Explorer / Agent，"
            "Git 面板会显示 Unavailable"
        )
        return
    try:
        ver = subprocess.run(["git", "--version"], capture_output=True,
                             text=True, timeout=10).stdout.strip()
        print(f"[env] Git {ver or '(installed)'}")
    except Exception as e:  # noqa: BLE001
        warnings.append(f"Git: 检测失败（{e}）")


def _check_model_api(cfg, warnings: list[str]) -> None:
    if cfg.api_key:
        print("[env] Model API key: configured（不会显示明文）")
    else:
        warnings.append(
            "Model API Key missing —— 请将 .env.example 复制为 .env 并填入 DEEPSEEK_API_KEY；"
            "UI 会显示 Model API Key Required"
        )


def _check_workspace(cfg, warnings: list[str]) -> None:
    try:
        cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
        print(f"[env] Workspace dir: {cfg.workspace_dir}")
    except OSError as e:
        warnings.append(f"Workspace dir 不可写（{cfg.workspace_dir}）：{e}")


def _find_free_port(host: str, preferred: int) -> int | None:
    """探测可用端口。

    - preferred > 0：优先使用该端口；被占用返回 None（调用方报明确错误）。
    - preferred <= 0：自动选择空闲端口并返回实际端口号。
    """
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        try:
            s.bind((host, preferred))
            return s.getsockname()[1]
        except OSError:
            if preferred > 0:
                return None
        try:
            s.bind((host, 0))
            return s.getsockname()[1]
        except OSError:
            return None


def main() -> int:
    cfg = get_config()
    print("=" * 60)
    print(BANNER)
    print("=" * 60)

    warnings: list[str] = []
    _check_python()
    _check_git(warnings)
    _check_model_api(cfg, warnings)
    _check_workspace(cfg, warnings)
    for w in warnings:
        print(f"[warn] {w}")

    host = cfg.host
    port = cfg.port

    # 端口策略：显式端口被占用 -> 明确错误；PORT=0 -> 自动选端口并打印实际 URL
    if port > 0:
        actual = _find_free_port(host, port)
        if actual is None:
            print(f"\n[error] 端口 {host}:{port} 已被占用。")
            print("        请换一个端口，例如：PORT=8801 python run.py")
            print("        或让服务自动选择空闲端口：PORT=0 python run.py")
            return 2
    else:
        actual = _find_free_port(host, 0)
        if actual is None:
            print("\n[error] 无法分配空闲端口。")
            return 2

    url = f"http://{host}:{actual}"
    print()
    print(BANNER)
    print("Server running at:")
    print(f"  {url}")
    print("(默认只监听本机回环地址 127.0.0.1；如需局域网访问请显式设置 HOST=0.0.0.0)")
    print()

    import uvicorn
    uvicorn.run("app.server:app", host=host, port=actual, log_level="info")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
