#!/usr/bin/env python3
"""Benchmark：用一组固定任务评估 Agent 效果（PHASE 8）。

运行（需 .env 配置真实 Key）：
  source .venv/bin/activate
  python benchmarks/benchmark.py

输出每任务：成功/失败、轮次、耗时、修复次数。
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from app.agent.loop import AgentLoop  # noqa: E402
from app.config import get_config  # noqa: E402
from app.model.client import DeepSeekClient  # noqa: E402
from app.security.sandbox import default_sandbox  # noqa: E402
from app.tools.registry import build_registry  # noqa: E402

TASKS = [
    {
        "name": "create_hello",
        "task": "在 workspace 中创建文件 hello.py，内容为打印 'hello from v4 flash' 的函数 main()，并运行验证输出。",
    },
    {
        "name": "find_and_describe",
        "task": "列出 workspace 下的文件，读取第一个 .txt 文件并汇报其前 3 行内容。",
    },
    {
        "name": "fix_add",
        "task": "在 workspace 中创建一个 add.py，包含 add(a,b) 函数与一个会失败的测试断言，然后修复代码使测试通过。",
    },
]


def run_benchmark(tasks=None, repeat: int = 1) -> dict:
    cfg = get_config()
    api_key = cfg.require_api_key()
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    sandbox = default_sandbox()
    registry = build_registry(sandbox)
    client = DeepSeekClient(api_key=api_key, base_url=cfg.base_url, model=cfg.model,
                            timeout=cfg.request_timeout)
    loop = AgentLoop(client, registry, max_turns=cfg.max_turns, max_repairs=cfg.max_repairs,
                     log_dir=cfg.project_root / "logs")
    results = []
    try:
        for t in (tasks or TASKS):
            for r in range(repeat):
                start = time.time()
                res = loop.run(t["task"])
                elapsed = time.time() - start
                results.append({
                    "name": t["name"],
                    "completed": res.completed,
                    "stopped_by": res.stopped_by,
                    "turns": res.turns_used,
                    "repairs": res.repair_attempts,
                    "elapsed_s": round(elapsed, 2),
                    "log": res.log_path,
                })
    finally:
        client.close()
    return results


def main() -> int:
    results = run_benchmark()
    out_path = PROJECT_ROOT / "benchmarks" / "results.json"
    out_path.write_text(json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    success = sum(1 for r in results if r["completed"])
    print(f"Benchmark 完成: {success}/{len(results)} 成功")
    for r in results:
        print(f"  {r['name']:20s} completed={r['completed']} stopped={r['stopped_by']} "
              f"turns={r['turns']} repairs={r['repairs']} time={r['elapsed_s']}s")
    print(f"结果已写入: {out_path}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
