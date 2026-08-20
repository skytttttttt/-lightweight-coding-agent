"""Benchmark Runner：为每个 Case 在隔离目录运行真实 Agent，记录原始执行数据。

用法：
  python benchmarks/runner.py --tag round1 [--case case_001_simple_bug] [--max-turns 30]

说明：
- 每个 Case 从 benchmarks/cases/case_XXX 复制种子代码到 workspace/bench_case_XXX（不含 task.md/META.json）
- 执行前对种子代码做 sha256 快照（results/<tag>/<case>_seed.json），供 evaluator 计算文件改动
- 执行 AgentLoop 运行 task.md 描述的真实任务
- 原始结果写入 results/<tag>/raw/<case>.json（不包含 API Key 与完整 reasoning）
"""
from __future__ import annotations

import argparse
import json
import shutil
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

CASES_DIR = PROJECT_ROOT / "benchmarks" / "cases"
RESULTS_DIR = PROJECT_ROOT / "benchmarks" / "results"
MAX_OUTPUT_CHARS = 400
IGNORE_PARTS = {"__pycache__", ".pytest_cache", ".git"}


def sha256_file(path: Path) -> str:
    import hashlib
    h = hashlib.sha256()
    h.update(path.read_bytes())
    return h.hexdigest()


def _keep(p: Path) -> bool:
    """跳过缓存/版本控制目录与说明文件。"""
    if p.name in ("task.md", "META.json"):
        return False
    return not any(part in IGNORE_PARTS for part in p.parts)


def snapshot_seed(case_dir: Path) -> dict:
    """对 case 目录下全部种子文件（排除 task.md/META.json 与缓存）做快照。"""
    snap = {}
    for p in sorted(case_dir.rglob("*")):
        if p.is_file() and _keep(p):
            rel = p.relative_to(case_dir).as_posix()
            snap[rel] = sha256_file(p)
    return snap


def prepare_workspace(case_dir: Path, name: str) -> Path:
    """重建隔离工作目录 workspace/bench_case_XXX 并复制种子代码（不含缓存）。"""
    target = PROJECT_ROOT / "workspace" / f"bench_{name}"
    if target.exists():
        shutil.rmtree(target)
    target.mkdir(parents=True)
    for p in sorted(case_dir.rglob("*")):
        if p.is_file() and _keep(p):
            rel = p.relative_to(case_dir)
            dst = target / rel
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(p, dst)
    return target


def run_one(name: str, task: str, max_turns: int, system_prompt: str | None = None) -> dict:
    cfg = get_config()
    api_key = cfg.require_api_key()
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    sandbox = default_sandbox()
    registry = build_registry(sandbox)
    client = DeepSeekClient(api_key=api_key, base_url=cfg.base_url, model=cfg.model,
                            timeout=cfg.request_timeout)
    loop = AgentLoop(client, registry, max_turns=max_turns, max_repairs=cfg.max_repairs,
                     log_dir=cfg.project_root / "logs")
    start = time.time()
    try:
        result = loop.run(task, system_prompt=system_prompt)
    finally:
        client.close()
    elapsed = round(time.time() - start, 2)

    # 精简轨迹：只保留工具调用名/参数/输出摘要，绝不包含 API Key 与完整 reasoning
    trace = []
    for turn in result.trace:
        tools = []
        for tc in turn.get("tool_calls", []):
            tools.append({"name": tc.get("name"), "arguments": str(tc.get("arguments", ""))[:300]})
        for tr in turn.get("tool_results", []):
            out = str(tr.get("output", ""))
            tools.append({"name": tr.get("name"), "output_head": out[:MAX_OUTPUT_CHARS]})
        trace.append({"tools": tools})
    return {
        "case_id": name,
        "task": task,
        "completed": result.completed,
        "stopped_by": result.stopped_by,
        "turns_used": result.turns_used,
        "repair_attempts": result.repair_attempts,
        "error": result.error,
        "log_path": result.log_path,
        "elapsed": elapsed,
        "trace": trace,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tag", default="round1", help="运行轮次标签（round1/round2）")
    ap.add_argument("--case", default=None, help="只运行指定 case（可选）")
    ap.add_argument("--max-turns", type=int, default=None)
    ap.add_argument("--prompt-file", default=None,
                    help="指定 .py 文件（含 SYSTEM_PROMPT 变量）作为系统提示词；默认用当前 prompt.py")
    args = ap.parse_args()

    cfg = get_config()
    max_turns = args.max_turns or cfg.max_turns

    system_prompt = None
    if args.prompt_file:
        import importlib.util
        pfile = Path(args.prompt_file)
        spec = importlib.util.spec_from_file_location("bench_prompt", pfile)
        mod = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(mod)
        system_prompt = getattr(mod, "SYSTEM_PROMPT", None)
        if not system_prompt:
            print(f"错误: {pfile} 未定义 SYSTEM_PROMPT")
            sys.exit(1)

    tag_dir = RESULTS_DIR / args.tag
    raw_dir = tag_dir / "raw"
    raw_dir.mkdir(parents=True, exist_ok=True)

    cases = sorted(CASES_DIR.iterdir()) if not args.case else [CASES_DIR / args.case]
    cases = [c for c in cases if c.is_dir() and c.name.startswith("case_")]
    if not cases:
        print(f"未找到 case 目录: {CASES_DIR}")
        sys.exit(1)

    summary = []
    for cdir in cases:
        name = cdir.name
        task = (cdir / "task.md").read_text(encoding="utf-8").strip()
        print(f"[{args.tag}] 运行 {name} ...", flush=True)
        try:
            prepare_workspace(cdir, name)
            snap = snapshot_seed(cdir)
            (tag_dir / f"{name}_seed.json").write_text(
                json.dumps(snap, ensure_ascii=False, indent=2), encoding="utf-8")
            record = run_one(name, task, max_turns, system_prompt)
        except Exception as e:  # noqa: BLE001
            record = {"case_id": name, "task": task, "runner_error": repr(e),
                      "completed": False, "stopped_by": "runner_error",
                      "turns_used": 0, "repair_attempts": 0, "elapsed": 0, "trace": []}
        (raw_dir / f"{name}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        summary.append({"case_id": name, "completed": record.get("completed"),
                        "stopped_by": record.get("stopped_by"),
                        "turns_used": record.get("turns_used"),
                        "elapsed": record.get("elapsed")})
        print(f"    -> completed={record.get('completed')} stopped_by={record.get('stopped_by')} "
              f"turns={record.get('turns_used')} elapsed={record.get('elapsed')}s", flush=True)

    (tag_dir / "summary.json").write_text(
        json.dumps({"tag": args.tag, "cases": summary}, ensure_ascii=False, indent=2),
        encoding="utf-8")
    ok = sum(1 for s in summary if s["completed"])
    print(f"[{args.tag}] 完成 {len(summary)} 个 case，completed={ok}/{len(summary)}")


if __name__ == "__main__":
    main()
