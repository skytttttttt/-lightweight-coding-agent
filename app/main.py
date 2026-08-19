"""CLI 入口：python -m app.main "任务描述"

示例：
  python -m app.main "修复这个项目的登录 Bug"
"""
from __future__ import annotations

import sys

from app.agent.loop import AgentLoop
from app.config import get_config
from app.model.client import DeepSeekClient
from app.security.sandbox import default_sandbox
from app.tools.registry import build_registry


def run_task(task: str) -> None:
    cfg = get_config()
    try:
        api_key = cfg.require_api_key()
    except RuntimeError as e:
        print(f"[error] {e}", file=sys.stderr)
        sys.exit(2)

    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    sandbox = default_sandbox()
    registry = build_registry(sandbox)
    client = DeepSeekClient(api_key=api_key, base_url=cfg.base_url, model=cfg.model,
                            timeout=cfg.request_timeout)
    loop = AgentLoop(client, registry, max_turns=cfg.max_turns, max_repairs=cfg.max_repairs,
                     log_dir=cfg.project_root / "logs")
    try:
        result = loop.run(task)
    finally:
        client.close()

    print("=" * 60)
    print(f"任务: {result.task}")
    print(f"轮次: {result.turns_used}  停止原因: {result.stopped_by}  修复次数: {result.repair_attempts}")
    if result.error:
        print(f"错误: {result.error}")
    if result.log_path:
        print(f"日志: {result.log_path}")
    print("=" * 60)
    print(result.final_answer or "(无最终文本)")


def main() -> int:
    args = sys.argv[1:]
    if not args:
        print("用法: python -m app.main \"任务描述\"", file=sys.stderr)
        return 1
    task = " ".join(args)
    run_task(task)
    return 0


if __name__ == "__main__":
    sys.exit(main())
