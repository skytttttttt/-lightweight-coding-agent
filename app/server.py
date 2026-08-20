"""API Server：POST /v1/agent/run

启动：
  uvicorn app.server:app --host 0.0.0.0 --port 8000

请求体：
  {"task": "任务描述"}
"""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.loop import AgentLoop
from app.config import get_config
from app.model.client import DeepSeekClient
from app.security.sandbox import default_sandbox
from app.tools.registry import build_registry

app = FastAPI(title="V4-Flash Coding Agent", version="1.1.0")

WEB_DIR = get_config().project_root / "web"


class RunRequest(BaseModel):
    task: str = Field(..., description="编程任务描述")


class RunResponse(BaseModel):
    task: str
    completed: bool
    stopped_by: str
    turns_used: int
    repair_attempts: int
    final_answer: str
    error: Optional[str] = None
    log_path: Optional[str] = None
    reasoning_log: Optional[str] = None
    trace: Optional[list] = None


def _build_runner():
    cfg = get_config()
    try:
        api_key = cfg.require_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    sandbox = default_sandbox()
    registry = build_registry(sandbox)
    client = DeepSeekClient(api_key=api_key, base_url=cfg.base_url, model=cfg.model,
                            timeout=cfg.request_timeout)
    loop = AgentLoop(client, registry, max_turns=cfg.max_turns, max_repairs=cfg.max_repairs,
                     log_dir=cfg.project_root / "logs")
    return client, loop


@app.post("/v1/agent/run")
def agent_run(req: RunRequest) -> RunResponse:
    client, loop = _build_runner()
    try:
        result = loop.run(req.task)
    finally:
        client.close()
    return RunResponse(
        task=result.task,
        completed=result.completed,
        stopped_by=result.stopped_by,
        turns_used=result.turns_used,
        repair_attempts=result.repair_attempts,
        final_answer=result.final_answer,
        error=result.error or None,
        log_path=result.log_path,
        reasoning_log=result.reasoning_log,
        trace=result.trace,
    )


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": get_config().model}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# 静态资源（Web 页面）
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
