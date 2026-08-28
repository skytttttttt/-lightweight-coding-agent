"""API Server：POST /v1/agent/run + SSE streaming + workspace APIs

启动（推荐使用 run.py，支持 Environment Check / 端口策略 / URL 打印）：
  python run.py                 # 默认 127.0.0.1:8000
  HOST=127.0.0.1 PORT=8801 python run.py
  uvicorn app.server:app        # 等价于上面默认配置

安全边界：默认只绑定 127.0.0.1（本机回环），绝不默认暴露到局域网。
非 .env 环境变量：HOST / PORT 可覆盖绑定地址与端口。

请求体：
  {"task": "任务描述"}
"""
from __future__ import annotations

import asyncio
import json
import re
import shutil
import subprocess
import threading
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import FileResponse, JSONResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

from app.agent.loop import AgentLoop
from app.config import get_config
from app.model.client import DeepSeekClient
from app.security.sandbox import Sandbox, SandboxError, default_sandbox
from app.tools.git import git_diff, git_status
from app.tools.registry import build_registry

app = FastAPI(title="V4-Flash Coding Agent", version="1.2.0")

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


def _build_runner(progress_callback=None):
    cfg = get_config()
    try:
        api_key = cfg.require_api_key()
    except RuntimeError as e:
        raise HTTPException(status_code=400, detail=str(e))
    cfg.workspace_dir.mkdir(parents=True, exist_ok=True)
    # P0：Agent 与 File Explorer / Git 同源——必须使用当前激活项目的 Project Root。
    # 未加载项目时拒绝运行，避免“左侧空态 / 右侧操作另一根”的不一致。
    active = get_active_project()
    if active is None:
        raise HTTPException(status_code=400, detail="尚未加载项目：请先在左侧点击 Upload Folder 上传一个项目文件夹")
    sandbox = Sandbox(cfg.workspace_dir, project_root=active["root"])
    registry = build_registry(sandbox)
    client = DeepSeekClient(api_key=api_key, base_url=cfg.base_url, model=cfg.model,
                            timeout=cfg.request_timeout)
    loop = AgentLoop(client, registry, max_turns=cfg.max_turns, max_repairs=cfg.max_repairs,
                     log_dir=cfg.project_root / "logs", progress_callback=progress_callback)
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


# ---------- SSE Streaming ----------

SSE_DONE = object()

# 运行取消管理（cancellation glue，不改 Agent 行为）：
#   _RUN_CANCEL[run_id] = threading.Event —— Stop / 超时 / SSE 断开时 set 该事件，
#   AgentLoop.run(cancel_event=...) 检测到后立即停止执行（不再调用工具 / 写文件）。
_RUN_CANCEL_LOCK = threading.Lock()
_RUN_CANCEL: dict = {}


def _register_run() -> tuple[int, threading.Event]:
    run_id = threading.get_ident()
    ev = threading.Event()
    with _RUN_CANCEL_LOCK:
        _RUN_CANCEL[run_id] = ev
    return run_id, ev


def _unregister_run(run_id: int) -> None:
    with _RUN_CANCEL_LOCK:
        _RUN_CANCEL.pop(run_id, None)


def _request_cancel(run_id: int) -> bool:
    with _RUN_CANCEL_LOCK:
        ev = _RUN_CANCEL.get(run_id)
    if ev is not None:
        ev.set()
        return True
    return False


class CancelRequest(BaseModel):
    run_id: Optional[int] = Field(None, description="运行线程 runtime id；为空则取消全部运行")


@app.post("/api/agent/cancel")
def agent_cancel(req: CancelRequest) -> dict:
    """请求取消正在运行的 Agent（Stop 按钮后端入口）。

    仅 set cancellation event；loop 检测到取消后立即停止执行并推送 CANCELLED 状态。
    """
    cancelled = False
    if req.run_id:
        cancelled = _request_cancel(req.run_id) or cancelled
    else:
        with _RUN_CANCEL_LOCK:
            ids = list(_RUN_CANCEL.keys())
        for rid in ids:
            cancelled = _request_cancel(rid) or cancelled
    return {"ok": True, "cancelled": cancelled, "active_runs": len(_RUN_CANCEL)}


@app.get("/api/agent/status")
def agent_status() -> dict:
    """查询当前 Agent 运行状态（浏览器刷新恢复用，全部来自真实后端状态）。

    - running：是否有 Agent 正在运行
    - run_id：当前运行线程 runtime id（有则返回，供 Stop/Reconnecting 用）
    - project：当前激活项目 {name, root}（无则 null）
    """
    active = get_active_project()
    with _RUN_CANCEL_LOCK:
        running = bool(_RUN_CANCEL)
        run_ids = list(_RUN_CANCEL.keys())
    return {
        "running": running,
        "run_id": run_ids[0] if run_ids else None,
        "project": {"name": active["name"], "root": str(active["root"])} if active else None,
    }


def _request_cancel_all() -> bool:
    """取消全部正在运行的 Agent（项目切换 / 上传激活新项目时调用，保证 session 不跨项目）。"""
    with _RUN_CANCEL_LOCK:
        ids = list(_RUN_CANCEL.keys())
    cancelled = False
    for rid in ids:
        cancelled = _request_cancel(rid) or cancelled
    return cancelled


def _sse(data: dict) -> str:
    return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"


@app.post("/v1/agent/run/stream")
async def agent_run_stream(req: RunRequest):
    """SSE 流式运行 Agent，实时推送 thinking / tool_start / tool_end / complete / cancelled / error 事件。

    取消链路（Stop / 超时 / SSE 断开）：
      UI Stop -> POST /api/agent/cancel -> 设置 cancel_event
      AgentLoop 在每轮 / 每个工具前检测 -> 立即停止（不再调工具 / 写文件）
      -> 线程结束 -> SSE 推送 {event: "cancelled", data: {stopped_by:"cancelled", ...}}
      -> 前端显示 CANCELLED
    服务端 300s 超时与客户端断开也会请求取消，避免后台线程空转 / 继续修改文件。
    """
    queue: asyncio.Queue = asyncio.Queue()
    loop_result_holder = {"result": None}
    exception_holder = {"error": None}
    run_id, cancel_event = _register_run()

    def progress_callback(event: str, payload: dict) -> None:
        try:
            # 同步回调中向 async queue 放入事件
            asyncio.run_coroutine_threadsafe(queue.put({"event": event, "data": payload}), event_loop)
        except Exception:
            pass

    def run_agent() -> None:
        client = None
        loop = None
        try:
            client, loop = _build_runner(progress_callback=progress_callback)
            result = loop.run(req.task, cancel_event=cancel_event)
            loop_result_holder["result"] = result
        except Exception as e:  # noqa: BLE001
            exception_holder["error"] = str(e)
        finally:
            if client is not None:
                client.close()
            _unregister_run(run_id)
            asyncio.run_coroutine_threadsafe(queue.put(SSE_DONE), event_loop)

    def _final_payload(result) -> dict:
        return {
            "task": result.task,
            "completed": result.completed,
            "stopped_by": result.stopped_by,
            "turns_used": result.turns_used,
            "repair_attempts": result.repair_attempts,
            "final_answer": result.final_answer,
            "error": result.error,
            "log_path": result.log_path,
            "trace": result.trace,
        }

    event_loop = asyncio.get_running_loop()
    thread = threading.Thread(target=run_agent, daemon=True)
    thread.start()

    async def event_generator():
        try:
            while True:
                try:
                    item = await asyncio.wait_for(queue.get(), timeout=300.0)
                except asyncio.TimeoutError:
                    # 服务端超时：请求取消后台运行并返回 error
                    _request_cancel(run_id)
                    yield _sse({"event": "error", "data": {
                        "error": "流式响应超时（已请求取消后台运行）", "stopped_by": "timeout"}})
                    return
                if item is SSE_DONE:
                    break
                yield _sse(item)

            # 发送最终 complete / cancelled / error 事件（对应 loop 的真实终态）
            result = loop_result_holder["result"]
            if exception_holder["error"]:
                _request_cancel(run_id)
                yield _sse({"event": "error", "data": {
                    "error": exception_holder["error"], "stopped_by": "error"}})
            elif result is not None:
                if result.stopped_by == "cancelled":
                    yield _sse({"event": "cancelled", "data": _final_payload(result)})
                elif result.error:
                    yield _sse({"event": "error", "data": _final_payload(result)})
                else:
                    yield _sse({"event": "complete", "data": _final_payload(result)})
        finally:
            # 客户端断开（GeneratorExit）时请求取消后台线程，避免 Agent 继续调用工具/修改文件
            try:
                _request_cancel(run_id)
            finally:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ---------- 激活项目状态（P0：单一 Project Root 同源） ----------
# 初始无激活项目：File Explorer 空态，/api/git 返回空、Agent 拒绝运行；
# 上传文件夹成功后建立/切换激活项目根（File Explorer / Agent / Git 三端同源指向它）。
DEFAULT_PROJECT_NAME = "project"
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_PROJECT: Optional[dict] = None  # {"name": str, "root": Path}


def _project_slug(name: str) -> Optional[str]:
    """生成项目内部目录名（internal_slug）。

    展示名（display_name，如 "My Project 2" / "中文项目"）可以包含空格、中文、连字符；
    内部目录名（slug）只保留安全字符（字母/数字/-/_/中文），并把空白折叠为 '-'。
    仍禁止：.. 段、绝对路径、路径分隔符、控制字符、隐藏点前缀。
    """
    clean = (name or "").strip()
    if not clean or clean.startswith("."):
        return None
    if "/" in clean or "\\" in clean:
        return None
    if any(ord(ch) < 32 or ord(ch) == 127 for ch in clean):
        return None
    # 冒号在 macOS/Windows 都是非法文件名保留符，替换为 '-'
    slug = clean.replace(":", "-")
    # 空白 -> '-'，去掉首尾的点/横线，防止产生 ".." / 隐藏目录
    slug = re.sub(r"\s+", "-", slug).strip(".-")
    if not slug or ".." in slug:
        return None
    if len(slug) > 80:
        return None
    return slug


def get_active_project() -> Optional[dict]:
    with _ACTIVE_LOCK:
        return _ACTIVE_PROJECT


def set_active_project(name: str, root: Path) -> dict:
    global _ACTIVE_PROJECT
    with _ACTIVE_LOCK:
        proj = {"name": name, "root": Path(root).resolve()}
        _ACTIVE_PROJECT = proj
        return dict(proj)


projects_dir = get_config().workspace_dir / "projects"


def _active_sandbox() -> Optional[Sandbox]:
    """当前激活项目对应的 Sandbox（项目根参数化）；未加载项目返回 None（调用方按空态处理）。"""
    active = get_active_project()
    if active is None:
        return None
    return Sandbox(get_config().workspace_dir, project_root=active["root"])


# ---------- Workspace APIs ----------

SKIP_DIRS = {".git", ".venv", "__pycache__", "node_modules", "logs", ".pytest_cache"}
SKIP_FILES = {".env"}  # 精确名；.env* 变体（.env.example / .env.local 等）在下文统一跳过


def _build_tree(path: Path, sandbox) -> dict:
    """构建 workspace 文件树的一层（受 Sandbox 限制），目录节点带空 children 用于前端懒加载。"""
    try:
        resolved = sandbox.resolve(str(path))
    except SandboxError:
        return {"name": path.name, "type": "error", "rel_path": str(path), "children": []}
    if not resolved.exists():
        return {"name": path.name, "type": "missing", "rel_path": str(path), "children": []}
    rel = resolved.relative_to(sandbox.root) if resolved != sandbox.root else Path(".")
    if resolved.is_file():
        return {"name": resolved.name, "type": "file", "rel_path": str(rel)}
    children = []
    try:
        for entry in sorted(resolved.iterdir(), key=lambda e: (not e.is_dir(), e.name.lower())):
            if entry.is_dir() and entry.name in SKIP_DIRS:
                continue
            if entry.is_file() and (entry.name in SKIP_FILES or entry.name.startswith(".env")):
                continue
            child_rel = entry.relative_to(sandbox.root)
            child = {"name": entry.name, "type": "directory" if entry.is_dir() else "file", "rel_path": str(child_rel)}
            if entry.is_dir():
                child["children"] = []
            children.append(child)
    except PermissionError:
        pass
    return {"name": resolved.name, "type": "directory", "rel_path": str(rel), "children": children}


@app.get("/api/files")
def api_files(path: str = ".") -> dict:
    """获取当前激活项目文件树的一层；未加载项目时返回空态（无任何预设/Demo 文件）。"""
    active = get_active_project()
    if active is None:
        return {"active": False, "path": ".", "root_name": None, "root": None, "tree": None}
    sandbox = _active_sandbox()
    try:
        target = sandbox.resolve(path)
    except SandboxError as e:
        raise HTTPException(status_code=403, detail=str(e))
    tree = _build_tree(target, sandbox)
    return {"active": True, "path": tree.get("rel_path", str(path)),
            "root_name": active["name"], "root": str(sandbox.root), "tree": tree}


@app.get("/api/files/content")
def api_file_content(path: str = Query(..., description="Project Root 内相对路径")) -> dict:
    """读取 Project Root 内文本文件内容（只读；Web UI 文件预览用，不进入 Agent Runtime）。

    路径经 Sandbox 解析，逃逸 / 敏感路径被拒绝；二进制 / 非 UTF-8 / 超大文件仅提示不支持。
    """
    sandbox = _active_sandbox()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="尚未加载项目")
    try:
        target = sandbox.resolve(path)
    except SandboxError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if not target.is_file():
        raise HTTPException(status_code=404, detail="路径不存在或不是文件")
    size = target.stat().st_size
    if size > 512 * 1024:
        return {"ok": False, "path": str(path), "detail": f"文件过大（{size} bytes > 512KB），仅支持文本预览",
                "content": "", "size": size, "lines": 0}
    try:
        data = target.read_bytes()
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"读取失败: {e}")
    if b"\x00" in data:
        return {"ok": False, "path": str(path), "detail": "二进制文件不支持预览",
                "content": "", "size": size, "lines": 0}
    try:
        text = data.decode("utf-8")
    except UnicodeDecodeError:
        return {"ok": False, "path": str(path), "detail": "非 UTF-8 文本，不支持预览",
                "content": "", "size": size, "lines": 0}
    rel = str(target.relative_to(sandbox.root))
    lines = text.count("\n") + (0 if text.endswith("\n") else 1)
    return {"ok": True, "path": rel, "content": text, "size": size, "lines": lines}


class DeleteFileRequest(BaseModel):
    path: str = Field(..., description="Project Root 内相对路径（文件或目录）")


@app.post("/api/files/delete")
def api_files_delete(req: DeleteFileRequest) -> dict:
    """删除 Project Root 内文件或目录（目录递归删除整个子树）。

    安全约束（与上传接口同等严格）：
    - 路径经 Sandbox 解析：拒绝 ../、绝对路径、控制字符、敏感段（.git/.env/.ssh/.aws/.kube 等）
    - 拒绝删除项目根目录本身
    - 文件用 unlink；目录用 shutil.rmtree 递归删除
    - 成功返回被删路径清单（Project Root 相对路径）
    """
    sandbox = _active_sandbox()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="尚未加载项目")
    raw = (req.path or "").strip().replace("\\", "/")
    if not raw:
        raise HTTPException(status_code=400, detail="删除路径不能为空")
    if any(ord(c) < 32 for c in raw):
        raise HTTPException(status_code=400, detail="路径包含控制字符")
    try:
        target = sandbox.resolve(raw)
    except SandboxError as e:
        raise HTTPException(status_code=403, detail=str(e))
    if target == sandbox.root:
        raise HTTPException(status_code=400, detail="不能删除项目根目录")
    if not target.exists():
        raise HTTPException(status_code=404, detail=f"路径不存在: {raw}")
    rel = str(target.relative_to(sandbox.root))
    deleted: list[str] = []
    try:
        if target.is_dir():
            # 递归收集被删路径（子级在前，便于 rmtree 后仍能完整上报清单）
            for p in sorted(target.rglob("*"), key=lambda x: len(x.parts), reverse=True):
                deleted.append(str(p.relative_to(sandbox.root)))
            deleted.append(rel)
            shutil.rmtree(target)
        else:
            target.unlink()
            deleted.append(rel)
    except OSError as e:
        raise HTTPException(status_code=500, detail=f"删除失败: {e}")
    return {"ok": True, "path": rel, "deleted": deleted, "count": len(deleted)}


# ---------- 文件上传（批量；保留相对路径，真实写入 Project Root） ----------

MAX_UPLOAD_BYTES = 20 * 1024 * 1024     # 单文件上限 20MB（文本）
MAX_UPLOAD_FILES = 100000               # 单批次文件数上限
UPLOAD_IGNORE_DIRS = {".git", "node_modules", "__pycache__", ".pytest_cache", ".venv", ".idea", ".vscode", "dist", "build", "logs"}
UPLOAD_IGNORE_FILES = {".DS_Store"}     # .env* 变体单独处理（见 _is_upload_ignored）


def _is_upload_ignored(rel_parts: list[str]) -> bool:
    """上传忽略规则：目录段命中忽略目录 / 隐藏目录；文件名为 .DS_Store / .env* 变体时忽略。

    仅用于过滤上传内容，不改变现有 Sandbox / Security 策略。
    """
    for part in rel_parts[:-1]:
        if part in UPLOAD_IGNORE_DIRS or part.startswith("."):
            return True
    name = rel_parts[-1]
    if name in UPLOAD_IGNORE_FILES or name.startswith(".env"):
        return True
    return False


class UploadFileItem(BaseModel):
    rel_path: str = Field(..., description="相对 Project Root 的目标路径（可含子目录）")
    content: str = Field("", description="UTF-8 文本内容")


class UploadBatchRequest(BaseModel):
    files: list[UploadFileItem] = Field(..., description="待上传文件列表（保留相对路径）")
    mode: Optional[str] = Field(None, description="冲突策略：None=探测（有冲突返回409不写入）；replace=覆盖；skip=跳过")
    project_name: Optional[str] = Field(None, description="目标项目名；文件夹上传取顶层目录名（建立/切换激活项目）；文件上传不传则写入当前激活项目")
    strip_top_dir: bool = Field(False, description="文件夹上传：从 rel_path 剥离顶层目录段（该段与 project_name 一致）")


@app.post("/api/files/upload")
async def api_upload_batch(req: UploadBatchRequest) -> dict:
    """批量上传文件/文件夹到当前 Project Root，保留相对路径与目录结构。

    - 每条 rel_path 经 Sandbox 解析：拒绝 ../、绝对路径逃逸、敏感段（.git/.env 等）
    - 忽略 .git / node_modules / __pycache__ / .DS_Store / .env* 等特殊内容
    - 目录自动创建；同名文件不静默覆盖（冲突检测 + Replace / Skip 策略）
    - 逐文件结果上报（uploaded / skipped / failed / rejected），失败不吞错误
    - 空目录无法通过浏览器 File API 表达，明确不接受（上传内容只能是文件）

    P0 项目根策略：
    - 文件夹上传（strip_top_dir=True + project_name=顶层目录名）：写入/建立 <workspace>/projects/<name>，
      上传成功后激活该项目根 —— File Explorer / Agent / Git 立即同源切换到该根（上传 project-B 即切换）。
    - 文件/多选上传（无 project_name）：追加写入当前激活项目根（保持原能力）。
    - 未加载项目时的普通文件上传：建立默认项目 "project" 并激活（仍走同一条真实路径）。
    """
    # ---- 解析目标项目根（单一根，与 File Explorer / Agent / Git 同源） ----
    active = get_active_project()
    project_name = (req.project_name or "").strip()
    if not project_name:
        project_name = active["name"] if active else DEFAULT_PROJECT_NAME
    display_name = project_name  # 用户可见项目名（可含空格/中文）
    safe_name = _project_slug(project_name)  # 内部目录名（仅安全字符）
    if safe_name is None:
        raise HTTPException(status_code=400,
                            detail=f"项目名不合法（禁止 .. / 绝对路径 / 控制字符）：{project_name or '(空)'}")
    target_root = projects_dir / safe_name
    sandbox = Sandbox(get_config().workspace_dir, project_root=target_root)

    if not req.files:
        raise HTTPException(status_code=400, detail="没有待上传的文件")
    if len(req.files) > MAX_UPLOAD_FILES:
        raise HTTPException(status_code=400, detail=f"单次最多上传 {MAX_UPLOAD_FILES} 个文件")
    mode = (req.mode or "").strip().lower()
    if mode not in ("", "replace", "skip"):
        raise HTTPException(status_code=400, detail="mode 仅支持 replace / skip")

    entries: list[dict] = []      # 已通过校验、可写入的条目
    conflicts: list[dict] = []    # 目标已存在（文件或目录冲突）
    rejected: list[dict] = []     # 校验失败条目（不写入）
    ignored = 0

    for item in req.files:
        raw = (item.rel_path or "").strip().replace("\\", "/")
        if not raw:
            rejected.append({"rel_path": item.rel_path or "", "detail": "空路径"})
            continue
        if raw.startswith("/") or "/:" in raw or (len(raw) >= 2 and raw[1] == ":"):
            rejected.append({"rel_path": raw, "detail": "绝对路径不允许（仅接受 Project Root 内相对路径）"})
            continue
        while raw.startswith("./"):
            raw = raw[2:]
        raw = raw.strip("/")
        if not raw:
            rejected.append({"rel_path": item.rel_path or "", "detail": "空路径"})
            continue
        if req.strip_top_dir:
            # 文件夹上传：剔除顶层目录段（顶层段即用户选择的 project_name，原始展示名），只保留项目内部相对路径
            head = raw.split("/", 1)
            if len(head) == 2 and head[0] == project_name:
                raw = head[1]
            if not raw:
                rejected.append({"rel_path": item.rel_path or "", "detail": "顶层目录剥离后为空路径"})
                continue
        parts = raw.split("/")
        if any(p in ("", ".", "..") for p in parts):
            rejected.append({"rel_path": raw, "detail": "路径含非法段（../ 或空段）"})
            continue
        if len(raw) > 1024:
            rejected.append({"rel_path": raw, "detail": "路径过长"})
            continue
        if any(ord(ch) < 32 or ord(ch) == 127 for ch in raw):
            rejected.append({"rel_path": raw, "detail": "路径含非法控制字符"})
            continue
        if len(parts[-1]) > 200:
            rejected.append({"rel_path": raw, "detail": "文件名过长"})
            continue
        if _is_upload_ignored(parts):
            ignored += 1
            continue
        size = len(item.content.encode("utf-8"))
        if size > MAX_UPLOAD_BYTES:
            rejected.append({"rel_path": raw, "detail": f"文件过大（{size} bytes > {MAX_UPLOAD_BYTES // (1024 * 1024)}MB），仅支持文本文件"})
            continue
        if "\x00" in item.content:
            rejected.append({"rel_path": raw, "detail": "仅支持文本文件（检测到二进制内容）"})
            continue
        try:
            target = sandbox.resolve(raw)
        except SandboxError as e:
            rejected.append({"rel_path": raw, "detail": str(e)})
            continue
        entry = {
            "rel_path": raw,
            "target": target,
            "content": item.content,
            "size": size,
            "exists": target.exists(),
            "is_dir_conflict": bool(target.exists() and target.is_dir()),
        }
        entries.append(entry)
        if entry["exists"]:
            conflicts.append({"rel_path": raw, "is_directory": entry["is_dir_conflict"]})

    # 探测模式（mode 为空）：存在冲突则 409，不写入任何文件
    if not mode and conflicts:
        return JSONResponse(status_code=409, content={
            "ok": False, "conflict": True, "mode": "detect",
            "conflicts": conflicts, "conflict_count": len(conflicts),
            "total": len(entries), "ignored": ignored,
            "rejected": rejected, "root": str(sandbox.root),
            "detail": f"发现 {len(conflicts)} 个同名文件，需指定 Replace 或 Skip 策略",
        })

    # 执行写入
    results: list[dict] = []
    uploaded = skipped = failed = 0
    for entry in entries:
        rel_path, target = entry["rel_path"], entry["target"]
        if entry["exists"] and mode == "skip":
            results.append({"rel_path": rel_path, "status": "skipped", "detail": "目标已存在，按 Skip 策略跳过"})
            skipped += 1
            continue
        if entry["is_dir_conflict"]:
            results.append({"rel_path": rel_path, "status": "failed", "detail": "目标路径是已存在的目录，无法写入文件"})
            failed += 1
            continue
        try:
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(entry["content"].encode("utf-8"))
            results.append({"rel_path": rel_path, "status": "uploaded",
                            "size": entry["size"], "overwritten": bool(entry["exists"])})
            uploaded += 1
        except OSError as e:
            results.append({"rel_path": rel_path, "status": "failed", "detail": f"写入失败: {e}"})
            failed += 1

    # 写入完成后：仅当有文件真实写入（uploaded > 0）时才切换/激活该项目根
    # （File Explorer / Agent / Git 同源）。uploaded == 0（全部被跳过/失败/拒绝）时
    # 保留当前激活项目，绝不无条件让一个“空项目”顶替当前项目。
    if uploaded > 0:
        # Project-Session 绑定：切换激活项目前，必须先结束当前项目上可能正在运行的
        # Agent session，禁止 Agent 跨项目继续执行（说明书 §24）。
        if active is None or active.get("root") != target_root:
            _request_cancel_all()
        active_project = set_active_project(name=display_name, root=target_root)
    else:
        active_project = None

    return {
        "ok": True, "mode": mode or "write",
        "total": len(entries), "uploaded": uploaded, "skipped": skipped,
        "failed": failed, "ignored": ignored,
        "results": results, "rejected": rejected,
        "conflict_count": len(conflicts),
        "root": str(sandbox.root),
        "active_project": active_project,
    }


@app.get("/api/git/status")
def api_git_status() -> dict:
    """获取当前激活项目 git 状态摘要。

    - 未加载项目：active=False（前端显示 Unavailable）
    - 非 Git 项目：is_git=False，changed_count=0，绝不伪造 changed_files
    - 正常 Git 项目：返回真实 changed_files / changed_count
    """
    sandbox = _active_sandbox()
    if sandbox is None:
        return {"active": False, "is_git": False, "output": "", "changed_files": [], "changed_count": 0}
    # 项目根自身不是 git 仓库（根下无 .git）时，即使外层目录属于其它 git 仓库，
    # 也绝不能把外层仓库的改动误报成当前项目的改动（P1-6：不伪造 changed_count）。
    if not (sandbox.root / ".git").exists():
        return {
            "active": True, "is_git": False,
            "output": "",
            "changed_files": [], "changed_count": 0,
            "detail": "Not a Git repository",
        }
    status_output = git_status(sandbox)
    lines = [ln for ln in status_output.splitlines() if ln.strip() and not ln.startswith("[")]
    # 非 Git 项目：git_status 返回 "[error] exit_code=128 ... fatal: not a git repository" 一类输出。
    # 绝不允许把 "fatal: not a git repository" 当成一个 changed file 上报。
    if any("[error]" in ln or "not a git repository" in ln for ln in status_output.splitlines()):
        return {
            "active": True, "is_git": False,
            "output": status_output,
            "changed_files": [], "changed_count": 0,
            "detail": "Not a Git repository",
        }
    return {
        "active": True, "is_git": True,
        "output": status_output,
        "changed_files": lines,
        "changed_count": len(lines),
    }


def _diff_stats(diff_text: str) -> str:
    """从 diff 文本统计 +N / -M 与文件数（只读摘要）。"""
    added = deleted = files = 0
    for line in diff_text.splitlines():
        if line.startswith("+++") or line.startswith("---"):
            continue
        if line.startswith("diff --git "):
            files += 1
        elif line.startswith("+"):
            added += 1
        elif line.startswith("-"):
            deleted += 1
    return f"+{added}  -{deleted}  · {files} file{'s' if files != 1 else ''}"


def _is_untracked(sandbox, path: str) -> bool:
    """判断 path 是否为 untracked 新文件（git ls-files 未跟踪）。"""
    try:
        resolved = sandbox.resolve(path)
        rel = str(resolved.relative_to(sandbox.root))
    except Exception:  # noqa: BLE001
        return False
    if not resolved.exists():
        return False
    proc = subprocess.run(
        ["git", "ls-files", "--error-unmatch", "--", rel],
        cwd=str(sandbox.root), capture_output=True, text=True)
    return proc.returncode != 0


@app.get("/api/git/diff")
def api_git_diff(path: str = Query("", description="Project Root 内相对路径；空则显示全部改动")) -> dict:
    """获取指定文件的 git diff（只读）。path 经 Sandbox 解析，逃逸 / 敏感路径被拒绝。"""
    sandbox = _active_sandbox()
    if sandbox is None:
        raise HTTPException(status_code=404, detail="尚未加载项目")
    # 非 git 项目：不进入外层仓库的 git diff（防止误报外层仓库改动），返回明确提示
    if not (sandbox.root / ".git").exists():
        return {"ok": True, "path": path, "diff": "",
                "detail": "Not a Git repository", "stats": ""}
    output = git_diff(sandbox, path)
    head, _, body = output.partition("\n")
    exit_code = 0
    if "exit_code=" in head:
        try:
            exit_code = int(head.split("exit_code=")[1].split()[0])
        except ValueError:
            exit_code = 1
    ok = exit_code == 0 and "[error]" not in head
    if not ok:
        # untracked 新文件：git diff 会报 "unknown revision / not in the working tree"。
        # 这类文件无 diff 可展示（内容即新增），返回明确提示而非让前端误判为错误。
        if "not in the working tree" in body or "unknown revision" in body:
            if path and _is_untracked(sandbox, path):
                return {"ok": True, "path": path, "diff": "",
                        "detail": "新文件（untracked）：暂无 git diff，完整内容见文件预览",
                        "stats": "new file"}
        return {"ok": False, "path": path, "detail": (body or head).strip(), "diff": "", "stats": ""}
    if not body.strip():
        # 已跟踪但无改动；若为 untracked 新文件则明确提示
        if path and _is_untracked(sandbox, path):
            return {"ok": True, "path": path, "diff": "",
                    "detail": "新文件（untracked）：暂无 git diff，完整内容见文件预览",
                    "stats": "new file"}
        return {"ok": True, "path": path, "diff": "", "detail": "该文件无未提交改动", "stats": ""}
    return {"ok": True, "path": path, "diff": body, "stats": _diff_stats(body)}


@app.get("/health")
def health() -> dict:
    return {"status": "ok", "model": get_config().model,
            "api_key_configured": bool(get_config().api_key)}


@app.get("/", include_in_schema=False)
def index() -> FileResponse:
    return FileResponse(WEB_DIR / "index.html")


# 静态资源（Web 页面）
if WEB_DIR.is_dir():
    app.mount("/static", StaticFiles(directory=WEB_DIR), name="static")
