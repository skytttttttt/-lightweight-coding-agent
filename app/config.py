"""应用配置：加载 .env，提供 DeepSeek 与项目路径配置。"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

from dotenv import load_dotenv

# 项目根目录（app 的上一级）——动态计算，可移植，不依赖任何作者机器路径
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# 加载 .env（存在时）
load_dotenv(PROJECT_ROOT / ".env")

_DEFAULT_HOST = "127.0.0.1"
_DEFAULT_PORT = 8000


def _env_host() -> str:
    return os.getenv("HOST", "").strip() or _DEFAULT_HOST


def _env_port() -> int:
    raw = os.getenv("PORT", "").strip()
    if raw:
        try:
            return int(raw)
        except ValueError:
            # 非法的 PORT 值不崩溃，回退默认端口
            return _DEFAULT_PORT
    return _DEFAULT_PORT


@dataclass(frozen=True)
class Config:
    api_key: str = field(default_factory=lambda: os.getenv("DEEPSEEK_API_KEY", "").strip())
    base_url: str = field(default_factory=lambda: os.getenv("DEEPSEEK_BASE_URL", "https://api.deepseek.com"))
    model: str = field(default_factory=lambda: os.getenv("DEEPSEEK_MODEL", "deepseek-v4-flash"))
    # 网络边界：默认只绑定本机回环地址，绝不默认暴露到局域网（可通过 HOST/PORT 显式覆盖）
    host: str = field(default_factory=_env_host)
    port: int = field(default_factory=_env_port)
    project_root: Path = PROJECT_ROOT
    workspace_dir: Path = PROJECT_ROOT / "workspace"
    max_turns: int = 30
    max_repairs: int = 2
    request_timeout: float = 120.0

    def require_api_key(self) -> str:
        """返回 API Key；缺失时抛出异常，绝不输出 Key 本身。"""
        if not self.api_key:
            raise RuntimeError(
                "缺少 DEEPSEEK_API_KEY：请将 .env.example 复制为 .env 并填入真实 API Key。"
            )
        return self.api_key


def get_config() -> Config:
    return Config()
