/* V4-Flash Coding Workspace — Agent-first UI (P0)
 * 数据流：POST /v1/agent/run/stream (SSE) + /api/files + /api/files/upload
 *        + /api/git/status + /api/git/diff + /health
 * 原则：真实数据优先；无 backend 的功能标注 PLACEHOLDER，不伪造功能假象。
 */

'use strict';

const $ = (id) => document.getElementById(id);
const clamp = (n, min, max) => Math.max(min, Math.min(max, n));

// ---------- State ----------
const state = {
  agentState: 'idle',
  task: '',
  startTime: null,
  currentTurn: 0,
  toolCounter: 0,
  pendingToolNodeId: null,
  toolNodes: new Map(),     // tool_call_id -> DOM 节点（P2-2：按 tool_call_id 关联状态）
  planSteps: [],        // [{label, state: pending|active|done}]
  toolsUsed: new Map(),
  filesChanged: new Map(),
  commands: [],
  verification: 'pending', // pending | pass | fail
  tests: null,             // {passed, failed} | null
  logPath: null,
  gitChanged: 0,
  isGit: true,             // 当前项目是否为 Git 仓库（真实来自 /api/git/status）
  gitStatusLines: [],
  sessions: JSON.parse(localStorage.getItem('v4_sessions') || '[]'),
  recent: JSON.parse(localStorage.getItem('v4_recent_tasks') || '[]'),
  abortController: null,
  activeDiff: null,
  gitFileStatus: {},   // rel_path -> status code（来自真实 git status，用于文件树标记）
  projectName: null,   // 当前激活项目名（来自真实上传/后端，File Explorer / Agent / Git 同源）
  projectRoot: null,   // 当前激活项目根（绝对路径）
  lastTask: '',        // 最近一次运行的任务（SSE 中断 Retry 用）
  cancelling: false,   // 是否正在请求取消（Stop 已按下，等待后端确认）
  agentEnded: false,   // 是否已收到 complete/error/cancelled 终态
  lastFocused: null,   // P3：Modal 关闭时恢复焦点
};

const STATES = {
  IDLE: 'idle',
  PLANNING: 'planning',
  THINKING: 'thinking',
  TOOL_CALLING: 'tool_calling',
  READING: 'reading',
  EDITING: 'editing',
  RUNNING: 'running',
  VERIFYING: 'verifying',
  REPAIRING: 'repairing',
  COMPLETED: 'completed',
  ERROR: 'error',
  CANCELLED: 'cancelled',
};

const STATE_LABEL = {
  idle: 'Idle',
  planning: 'Planning',
  thinking: 'Thinking',
  tool_calling: 'Using tool',
  reading: 'Reading code',
  editing: 'Editing files',
  running: 'Running command',
  verifying: 'Verifying',
  repairing: 'Repairing',
  completed: 'Completed',
  error: 'Error',
  cancelled: 'Cancelled',
};

// 单色 SVG 图标（克制，无 emoji）
const ICONS = {
  list_files: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>',
  read_file: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>',
  search_code: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/></svg>',
  write_file: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 20h9"/><path d="M16.5 3.5a2.1 2.1 0 013 3L7 19l-4 1 1-4L16.5 3.5z"/></svg>',
  edit_file: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M17 3a2.8 2.8 0 114 4L7.5 20.5 2 22l1.5-5.5L17 3z"/></svg>',
  run_command: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 3l14 9-14 9V3z"/></svg>',
  git_diff: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><circle cx="6" cy="6" r="3"/><circle cx="6" cy="18" r="3"/><path d="M6 9v6"/><circle cx="18" cy="6" r="3"/><circle cx="18" cy="18" r="3"/><path d="M18 9v2a3 3 0 01-3 3H9"/></svg>',
  run_command_default: '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M5 3l14 9-14 9V3z"/></svg>',
};

const MAX_VISIBLE_NODES = 8;
const MAX_OUTPUT_LEN = 2000;

// ---------- Helpers ----------
function esc(s) {
  return String(s ?? '')
    .replace(/&/g, '&amp;')
    .replace(/</g, '&lt;')
    .replace(/>/g, '&gt;')
    .replace(/"/g, '&quot;')
    .replace(/'/g, '&#39;');
}

function truncateOutput(text, max = MAX_OUTPUT_LEN) {
  const s = String(text ?? '');
  if (s.length <= max) return s;
  return s.slice(0, max) + '\n\n... (truncated; expand to view full output)';
}

function formatTime(ms) {
  const totalSeconds = Math.max(0, Math.floor(ms / 1000));
  const m = Math.floor(totalSeconds / 60);
  const s = totalSeconds % 60;
  return `${m}:${s.toString().padStart(2, '0')}`;
}

function nowStr() {
  return new Date().toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' });
}

// P3：Modal 焦点管理 —— 打开时保存触发元素并聚焦首元素，关闭时恢复焦点
function saveFocus() { state.lastFocused = document.activeElement; }
function restoreFocus() {
  const el = state.lastFocused;
  if (el && el.focus && typeof el.focus === 'function') { try { el.focus(); } catch (e) {} }
  state.lastFocused = null;
}

function showToast(message) {
  const toast = $('toast');
  toast.textContent = message;
  toast.classList.add('show');
  clearTimeout(showToast._t);
  showToast._t = setTimeout(() => toast.classList.remove('show'), 2400);
}

function saveRecent(task) {
  state.recent = [task, ...state.recent.filter((t) => t !== task)].slice(0, 6);
  localStorage.setItem('v4_recent_tasks', JSON.stringify(state.recent));
}

function saveSessions() {
  localStorage.setItem('v4_sessions', JSON.stringify(state.sessions.slice(0, 12)));
}

// ---------- Banner（P1-2：真实实现，替代缺失定义） ----------
// 类型：error / warn / info / success；支持 bannerRetry（可重试动作）与 bannerClose。
function showBanner(message, typeOrRetryable = 'err', detail = '', retryable = false, onRetry = null) {
  const banner = $('globalBanner');
  if (!banner) return;
  let type = 'err';
  if (typeof typeOrRetryable === 'string') type = typeOrRetryable;
  else if (typeOrRetryable === true) { type = 'err'; retryable = true; }
  const icon = { error: '✕', warn: '!', info: 'i', success: '✓' }[type] || '✕';
  banner.className = `global-banner show b-${type}`;
  const iconEl = $('bannerIcon');
  if (iconEl) { iconEl.textContent = icon; iconEl.className = `banner-icon ${type}`; }
  const textEl = $('bannerText');
  if (textEl) textEl.textContent = message;
  const detailEl = $('bannerDetail');
  if (detailEl) { detailEl.textContent = detail || ''; detailEl.hidden = !detail; }
  const retryBtn = $('bannerRetry');
  if (retryBtn) { retryBtn.hidden = !retryable; retryBtn.onclick = null; if (retryable) retryBtn.onclick = () => { if (typeof onRetry === 'function') onRetry(); }; }
  const closeBtn = $('bannerClose');
  if (closeBtn) closeBtn.onclick = hideBanner;
  banner.hidden = false;
}

function hideBanner() {
  const banner = $('globalBanner');
  if (!banner) return;
  banner.hidden = true;
  banner.className = 'global-banner';
  const retryBtn = $('bannerRetry');
  if (retryBtn) retryBtn.onclick = null;
}

// ---------- Health / model ----------
// P1-3：initial + periodic heartbeat（30s）。状态真实：
// CONNECTED（健康）/ DEGRADED（正在检查或服务异常）/ OFFLINE（无法连接）。
// 断开后 Connected 必须能变 Offline；恢复后 Offline -> Connected。
let healthTimer = null;
let healthState = 'unknown'; // unknown | connected | degraded | offline
async function checkHealth() {
  const dot = $('healthDot');
  const txt = $('healthText');
  if (!dot || !txt) return;
  dot.className = 'health-dot load';
  txt.textContent = 'Checking…';
  try {
    const r = await fetch('/health', { cache: 'no-store' });
    const data = await r.json();
    if (r.ok && data && typeof data === 'object' && data.status === 'ok') {
      const model = (data.model && String(data.model)) || 'deepseek-v4-flash';
      dot.className = 'health-dot ok';
      txt.textContent = `Connected · ${model}`;
      const envModel = $('envModel'); if (envModel) envModel.textContent = model;
      const agentModel = $('agentModel'); if (agentModel) agentModel.textContent = model;
      const cmdModel = $('cmdModel'); if (cmdModel) cmdModel.textContent = model; // P2-1：统一来自 /health
      const cmdState = $('cmdState'); if (cmdState) cmdState.dataset.health = 'ok';
      if (healthState !== 'connected') {
        healthState = 'connected';
        hideBanner(); // 恢复连接后清除 Offline banner
      }
      if (data.api_key_configured === false) {
        showBanner('Model API Key Required', 'warn',
          'Configure your API key to start the Agent — 请在 .env 中设置 DEEPSEEK_API_KEY。', false);
      }
      return true;
    }
    dot.className = 'health-dot err';
    txt.textContent = '服务异常';
    healthState = 'degraded';
    const cmdState = $('cmdState'); if (cmdState) cmdState.dataset.health = 'err';
    showBanner('API Offline', 'err', '后端服务不可用，请检查服务是否已启动。', true, () => { hideBanner(); checkHealth(); });
    return false;
  } catch (e) {
    dot.className = 'health-dot err';
    txt.textContent = '无法连接';
    healthState = 'offline';
    const cmdState = $('cmdState'); if (cmdState) cmdState.dataset.health = 'offline';
    showBanner('API Offline', 'err', '无法连接后端服务，重试中…。', true, () => { hideBanner(); checkHealth(); });
    return false;
  }
}

// ---------- Project / file tree ----------
const MAX_UPLOAD_BYTES = 20 * 1024 * 1024;   // 单文件上限 20MB（文本）
const MAX_UPLOAD_FILES = 100000;             // 单批次文件数上限

async function loadFileTree(path = '.') {
  try {
    const r = await fetch(`/api/files?path=${encodeURIComponent(path)}`);
    const data = await r.json();
    if (data.active === false) {
      // 初始无激活项目：Empty State（绝对不显示任何预设/Demo 文件）
      renderEmptyState();
      return;
    }
    if (data.root_name) {
      state.projectName = data.root_name;
      state.projectRoot = data.root || null;
      $('projectBadge').textContent = data.root_name;
      $('projectBadge').title = data.root || data.root_name;
      $('envProject').textContent = data.root || data.root_name;
    }
    renderFileTree(data.tree, $('fileTree'));
    // 项目根就绪后刷新 Run 可用态（避免"已加载项目但 Run 仍禁用"）
    if (typeof updateRunButtonState === 'function') updateRunButtonState();
    // 生命周期状态机：真实加载成功 -> PROJECT_READY
    setProjectLifecycle('PROJECT_READY');
  } catch (e) {
    $('fileTree').innerHTML = '<div class="tree-empty">加载失败</div>';
    setProjectLifecycle('PROJECT_ERROR', '加载文件树失败，请检查后端服务');
  }
}

// ---------- Project 生命周期状态机（说明书 §5） ----------
// NO_PROJECT -> LOADING_PROJECT -> PROJECT_READY / PROJECT_ERROR
// 全部状态来自真实后端 / 真实上传链路，禁止 mock。
const PROJECT_STATE = {
  NO_PROJECT: 'NO_PROJECT',
  LOADING_PROJECT: 'LOADING_PROJECT',
  PROJECT_READY: 'PROJECT_READY',
  PROJECT_ERROR: 'PROJECT_ERROR',
};
let projectLifecycle = PROJECT_STATE.NO_PROJECT;

function escapeHtml(s) {
  return String(s == null ? '' : s).replace(/[&<>"']/g, (c) => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;',
  }[c]));
}

function setProjectLifecycle(st, detail) {
  projectLifecycle = st;
  const tree = $('fileTree');
  if (!tree) return;
  if (st === PROJECT_STATE.NO_PROJECT) {
    // 空态渲染由 renderEmptyState() 负责
  } else if (st === PROJECT_STATE.LOADING_PROJECT) {
    tree.innerHTML = `
      <div class="tree-empty-state">
        <div class="tree-empty-title">Loading project…</div>
        <div class="tree-loading-bar"><span></span></div>
        <div class="tree-empty-sub">正在读取项目文件…</div>
      </div>`;
  } else if (st === PROJECT_STATE.PROJECT_ERROR) {
    tree.innerHTML = `
      <div class="tree-empty-state">
        <div class="tree-empty-icon">
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2"><path d="M12 8v4M12 16h.01"/><path d="M10.3 3.8L2.5 17a2 2 0 001.7 3h15.6a2 2 0 001.7-3L13.7 3.8a2 2 0 00-3.4 0z"/></svg>
        </div>
        <div class="tree-empty-title">Unable to load project</div>
        <div class="tree-empty-sub">${escapeHtml(detail || '加载失败')}</div>
        <button type="button" class="tree-empty-btn tree-empty-primary" id="treeErrorRetry">Retry</button>
      </div>`;
    const retry = $('treeErrorRetry');
    if (retry) retry.addEventListener('click', () => refreshFileTree());
  }
}

// ---------- Open Folder（说明书 §6：优先打开本地文件夹） ----------
// 使用浏览器 File System Access API（showDirectoryPicker）选择真实本地目录；
// 不支持时降级提示使用 Upload Folder。选择后目录内容经统一上传链路
// 安全导入 workspace/projects/<project-id>/（Mode B），最终路径由后端
// Sandbox / path validation 统一计算，前端绝不决定服务器最终路径。
async function openFolderWithPicker() {
  if (!window.showDirectoryPicker) {
    showBanner('Direct folder access not supported', 'warn',
      '当前浏览器不支持直接打开文件夹（需要 File System Access API），请改用 Upload Folder 上传文件夹。',
      false, null);
    setTimeout(() => { if ($('folderInput')) $('folderInput').click(); }, 0);
    return;
  }
  try {
    const dirHandle = await window.showDirectoryPicker({ mode: 'readwrite' });
    if (!dirHandle) return; // 用户取消
    setProjectLifecycle('LOADING_PROJECT');
    const items = [];
    let ignored = 0;
    const walk = async (handle, rel) => {
      for await (const [name, child] of handle.entries()) {
        if (child.kind === 'directory') {
          await walk(child, rel ? `${rel}/${name}` : name);
        } else {
          const relPath = rel ? `${rel}/${name}` : name;
          if (isUploadIgnored(relPath)) { ignored++; continue; }
          const file = await child.getFile();
          if (file.size > MAX_UPLOAD_BYTES) { ignored++; continue; }
          items.push({ rel_path: relPath, file, size: file.size });
        }
      }
    };
    await walk(dirHandle, '');
    if (!items.length) {
      setProjectLifecycle('PROJECT_ERROR', '所选文件夹为空或全部为忽略项');
      showToast('没有可上传的文件（全部为空、过大或属于忽略项）');
      return;
    }
    if (items.length > MAX_UPLOAD_FILES) {
      setProjectLifecycle('PROJECT_ERROR', '文件过多');
      showToast(`文件过多（${items.length} 个 > ${MAX_UPLOAD_FILES}），请分批上传`);
      return;
    }
    const dirs = new Set();
    items.forEach((it) => {
      const parts = it.rel_path.split('/');
      for (let i = 1; i < parts.length; i++) dirs.add(parts.slice(0, i).join('/'));
    });
    const totalSize = items.reduce((s, it) => s + it.size, 0);
    const projectName = dirHandle.name || 'project';
    // stripTopDir=false：showDirectoryPicker 返回的相对路径不含顶层目录段，
    // 直接用所选文件夹名作为项目显示名，后端负责安全路径与去重。
    openUploadPanel(items, dirs.size, totalSize, ignored, projectName, false);
  } catch (e) {
    if (e && e.name === 'AbortError') return; // 用户取消选择
    setProjectLifecycle('PROJECT_ERROR', e && e.message ? e.message : String(e));
    showToast('打开文件夹失败：' + (e && e.message ? e.message : e));
  }
}

// 初始 Empty State（无项目）：No project loaded + [Open Folder] [Upload Folder] [Upload Files]
function renderEmptyState() {
  state.projectName = null;
  state.projectRoot = null;
  setProjectLifecycle('NO_PROJECT');
  $('projectBadge').textContent = 'No project';
  $('projectBadge').title = '';
  $('envProject').textContent = 'No project loaded';
  $('fileTree').innerHTML = `
    <div class="tree-empty-state">
      <div class="tree-empty-icon">
        <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.2">
          <path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/>
          <path d="M12 11v5M9.5 13.5h5"/>
        </svg>
      </div>
      <div class="tree-empty-title">No project loaded</div>
      <div class="tree-empty-sub">Open a folder or upload one to start</div>
      <div class="tree-empty-actions">
        <button type="button" class="tree-empty-btn tree-empty-primary" id="treeEmptyOpenFolder">Open Folder</button>
        <button type="button" class="tree-empty-btn" id="treeEmptyUploadFolder">Upload Folder</button>
        <button type="button" class="tree-empty-btn" id="treeEmptyUploadFiles">Upload Files</button>
      </div>
      <div class="tree-empty-hint">Open Folder 需要浏览器 File System Access API；如不支持请使用 Upload Folder</div>
    </div>`;
  const openBtn = $('treeEmptyOpenFolder');
  if (openBtn) openBtn.addEventListener('click', () => openFolderWithPicker());
  const upFolder = $('treeEmptyUploadFolder');
  if (upFolder) upFolder.addEventListener('click', () => $('folderInput').click());
  const upFiles = $('treeEmptyUploadFiles');
  if (upFiles) upFiles.addEventListener('click', () => $('fileInput').click());
  updateRunButtonState();
}

// 刷新文件树时尽量保持展开/选中/滚动状态（上传 / Git 变更后不整树重置）
let _treeOpenSnapshot = null;
let _treeActiveSnapshot = null;
let _treeScrollTop = 0;

// 长按删除：长按(mousedown≈600ms)或右键(contextmenu)弹出删除菜单
let _pressTimer = null;
let _longPressFired = false;
let _suppressClick = false; // 长按/右键触发的 click 需吞掉，避免误展开/误预览

function snapshotTreeState() {
  const opened = [];
  document.querySelectorAll('#fileTree .tree-item[data-type="directory"]').forEach((el) => {
    const children = el.nextElementSibling;
    if (children && !children.classList.contains('collapsed')) opened.push(el.dataset.path);
  });
  return opened;
}

function refreshFileTree() {
  _treeOpenSnapshot = snapshotTreeState();
  const active = document.querySelector('#fileTree .tree-item.active');
  _treeActiveSnapshot = active ? active.dataset.path : null;
  const scroller = document.querySelector('.sidebar-scroll');
  if (scroller) _treeScrollTop = scroller.scrollTop;
  $('fileTree').innerHTML = '<div class="tree-empty">刷新中…</div>';
  loadFileTree('.').then(() => restoreTreeState());
}

async function restoreTreeState() {
  const opened = _treeOpenSnapshot || [];
  _treeOpenSnapshot = null;
  for (const p of opened) {
    const el = document.querySelector(`#fileTree .tree-item[data-type="directory"][data-path="${CSS.escape(p)}"]`);
    if (!el) continue;
    const children = el.nextElementSibling;
    if (!children) continue;
    if (children.classList.contains('collapsed')) {
      if (!children.dataset.loaded) {
        try {
          const r = await fetch(`/api/files?path=${encodeURIComponent(p)}`);
          const data = await r.json();
          const level = Math.max(0, Math.round(((parseInt(el.style.paddingLeft, 10) || 6) - 6) / 12));
          renderFileTree(data.tree, children, level);
          children.dataset.loaded = 'true';
        } catch (e) {
          children.innerHTML = '<div class="tree-empty" style="padding-left:14px">加载失败</div>';
          children.dataset.loaded = 'true';
        }
      }
      children.classList.remove('collapsed');
      const toggle = el.querySelector('.tree-toggle');
      if (toggle) toggle.classList.add('open');
    }
  }
  applyTreeStatusBadges();
  if (_treeActiveSnapshot) {
    const act = document.querySelector(`#fileTree .tree-item[data-path="${CSS.escape(_treeActiveSnapshot)}"]`);
    if (act) act.classList.add('active');
  }
  const scroller = document.querySelector('.sidebar-scroll');
  if (scroller) scroller.scrollTop = _treeScrollTop;
}

// ---------- Upload（文件 / 文件夹 → Project Root，保留相对路径） ----------
const UPLOAD_IGNORE_DIRS = new Set(['.git', 'node_modules', '__pycache__', '.pytest_cache', '.venv', '.idea', '.vscode', 'dist', 'build', 'logs']);
const UPLOAD_IGNORE_FILES = new Set(['.DS_Store']);

function isUploadIgnored(rel) {
  const parts = rel.split('/');
  for (const p of parts.slice(0, -1)) {
    if (UPLOAD_IGNORE_DIRS.has(p) || p.startsWith('.')) return true;
  }
  const name = parts[parts.length - 1];
  return UPLOAD_IGNORE_FILES.has(name) || name.startsWith('.env');
}

// 上传面板状态（真实数据，非假状态）
let uploadState = {
  items: [],        // {rel_path, file, size, status, detail}
  dirCount: 0,
  totalSize: 0,
  ignored: 0,
  active: false,
  controller: null,
  conflictMode: null, // 'replace' | 'skip' | null
  projectName: null,  // 目标项目名（文件夹上传=顶层目录名；文件上传=当前激活项目名）
  stripTopDir: false, // 文件夹上传：剥离顶层目录段后写入项目根
};

function upStatus(item, status, detail = '') {
  item.status = status;
  item.detail = detail;
}

function renderUploadPanel() {
  const items = uploadState.items;
  const n = items.length;
  const done = items.filter((i) => i.status === 'Completed' || i.status === 'Failed' || i.status === 'Skipped' || i.status === 'Cancelled').length;
  const uploading = items.filter((i) => i.status === 'Uploading').length;
  const pct = n ? Math.round(done / n * 100) : 0;
  let summary = `${n} files`;
  if (uploadState.dirCount) summary += ` · ${uploadState.dirCount} directories`;
  summary += ` · ${formatBytes(uploadState.totalSize)}`;
  if (uploadState.ignored) summary += ` · ${uploadState.ignored} 个特殊文件已忽略（.git/.DS_Store/.env 等）`;
  if (uploadState.active) summary += ` · Uploading ${uploading}/${n} (${pct}%)`;
  $('upSummary').textContent = summary;

  $('upProgressBar').style.width = `${pct}%`;
  $('upProgressText').textContent = `${done}/${n} · ${pct}%`;

  $('upBody').innerHTML = items.map((it, idx) => {
    const st = it.status;
    const cls = String(st).toLowerCase();
    const mark = st === 'Completed' ? '✓' : (st === 'Failed' || st === 'Cancelled') ? '✕' : st === 'Skipped' ? '–' : st === 'Uploading' ? '…' : '·';
    return `<div class="up-item" data-idx="${idx}">
      <span class="up-status up-${cls}">${mark}</span>
      <span class="up-path" title="${esc(it.rel_path)}">${esc(it.rel_path)}</span>
      <span class="up-size">${formatBytes(it.size)}</span>
      ${it.detail ? `<span class="up-detail">${esc(it.detail)}</span>` : ''}
    </div>`;
  }).join('');
}

function openUploadPanel(relItems, dirCount, totalSize, ignored, projectName, stripTopDir) {
  uploadState.items = relItems.map((it) => ({ rel_path: it.rel_path, file: it.file, size: it.size, status: 'Preparing', detail: '' }));
  uploadState.dirCount = dirCount;
  uploadState.totalSize = totalSize;
  uploadState.ignored = ignored;
  uploadState.active = false;
  uploadState.controller = null;
  uploadState.conflictMode = null;
  uploadState.projectName = projectName || null;
  uploadState.stripTopDir = !!stripTopDir;
  $('upRootPath').textContent = uploadState.projectName
    ? `Target project: ${uploadState.projectName}`
    : ($('projectBadge').title || $('envProject').textContent || '—');
  $('upConflict').hidden = true;
  $('upUpload').disabled = false;
  $('upCancel').disabled = false;
  renderUploadPanel();
  $('uploadModal').hidden = false;
  saveFocus(); // P3
  const firstBtn = $('upClose');
  if (firstBtn) firstBtn.focus(); // P3：focus first element
}

function closeUploadPanel() {
  if (uploadState.active) return; // 上传中不允许关闭
  uploadState.items = [];
  $('uploadModal').hidden = true;
  restoreFocus(); // P3
}

async function startUpload() {
  if (uploadState.active) return;
  uploadState.active = true;
  uploadState.controller = new AbortController();
  uploadState.items.forEach((it) => { if (it.status !== 'Completed' && it.status !== 'Failed' && it.status !== 'Skipped' && it.status !== 'Cancelled') upStatus(it, 'Uploading'); });
  $('upUpload').disabled = true;
  $('upCancel').disabled = false;
  $('upConflict').hidden = true;
  renderUploadPanel();
  try {
    // P2-6：编码安全 —— 宁可拒绝也不静默乱码：
    // 二进制（含 NUL 字节）与非法 UTF-8 文本直接拒绝，不静默改写用户文件。
    const payload = [];
    for (const it of uploadState.items) {
      const raw = await it.file.arrayBuffer();
      const bytes = new Uint8Array(raw);
      if (bytes.length > MAX_UPLOAD_BYTES) throw new Error(`文件过大（超过 ${MAX_UPLOAD_BYTES / (1024 * 1024)}MB）：${it.rel_path}`);
      if (bytes.includes(0)) throw new Error(`文件包含二进制内容，拒绝上传（仅支持文本）：${it.rel_path}`);
      let content;
      try {
        content = new TextDecoder('utf-8', { fatal: true }).decode(bytes);
      } catch (e) {
        throw new Error(`文件不是有效的 UTF-8 文本，拒绝上传：${it.rel_path}`);
      }
      payload.push({ rel_path: it.rel_path, content });
    }
    const body = { files: payload };
    if (uploadState.conflictMode) body.mode = uploadState.conflictMode;
    if (uploadState.projectName) body.project_name = uploadState.projectName;
    if (uploadState.stripTopDir) body.strip_top_dir = true;
    const r = await fetch('/api/files/upload', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify(body),
      signal: uploadState.controller.signal,
    });
    const data = await r.json().catch(() => ({}));

    if (r.status === 409 && data.conflict) {
      // 探测到同名冲突：询问用户处理策略，不写入任何文件
      const names = (data.conflicts || []).map((c) => c.rel_path).slice(0, 6);
      const more = (data.conflicts || []).length > 6 ? ` …共 ${data.conflicts.length} 个` : '';
      $('upConflictMsg').textContent = `发现 ${(data.conflicts || []).length} 个同名文件（${names.join('、')}${more}）。Replace All 覆盖 / Skip 跳过 / Cancel 取消。`;
      $('upConflict').hidden = false;
      uploadState.active = false;
      $('upUpload').disabled = false;
      renderUploadPanel();
      return;
    }
    if (!r.ok || !data.ok) {
      throw new Error(data.detail || `HTTP ${r.status}`);
    }

    // 应用真实结果到逐文件状态
    const byPath = {};
    (data.results || []).forEach((res) => { byPath[res.rel_path] = res; });
    (data.rejected || []).forEach((rej) => { byPath[rej.rel_path] = { status: 'failed', detail: rej.detail }; });
    uploadState.items.forEach((it) => {
      const res = byPath[it.rel_path];
      if (!res) { upStatus(it, 'Failed', '服务端未返回该文件结果'); return; }
      if (res.status === 'uploaded') upStatus(it, 'Completed', res.overwritten ? '已覆盖原文件' : '');
      else if (res.status === 'skipped') upStatus(it, 'Skipped', res.detail || '目标已存在，已跳过');
      else if (res.status === 'failed') upStatus(it, 'Failed', res.detail || '写入失败');
    });
    renderUploadPanel();

    const up = uploadState.items.filter((i) => i.status === 'Completed').length;
    const sk = uploadState.items.filter((i) => i.status === 'Skipped').length;
    const fa = uploadState.items.filter((i) => i.status === 'Failed').length;
    if (fa > 0) showToast(`上传完成但有错误：${up} uploaded / ${fa} failed`);
    else if (up > 0) showToast(`上传完成：${up} files${sk ? `（${sk} skipped）` : ''}`);
    else showToast('没有文件被写入（全部跳过或失败）');

    // 后端已建立/确认激活项目根 → 三端（File Explorer / Agent / Git）同源同步
    if (data.active_project) {
      // 项目切换：彻底清理旧项目的一切运行时状态（说明书 §23）
      clearProjectRuntimeState();
      state.projectName = data.active_project.name;
      state.projectRoot = data.active_project.root;
      $('projectBadge').textContent = data.active_project.name;
      $('projectBadge').title = data.active_project.root;
      $('envProject').textContent = data.active_project.root;
    }
    uploadState.projectName = null;
    uploadState.stripTopDir = false;
    // 真实联动：File Explorer 刷新 + Git 状态同步
    setProjectLifecycle('LOADING_PROJECT');
    refreshFileTree();
    loadGitStatus(true);
    uploadState.active = false;
    setTimeout(() => { if (!uploadState.active) closeUploadPanel(); }, 1400);
  } catch (e) {
    if (e.name === 'AbortError') {
      const left = uploadState.items.filter((i) => i.status === 'Uploading' || i.status === 'Preparing').length;
      showToast(`已取消上传（${left} 个文件未写入，已写入的保留）`);
    } else {
      showToast(`上传失败: ${e.message}`);
    }
    uploadState.items.forEach((it) => { if (it.status === 'Uploading') upStatus(it, 'Failed', e.name === 'AbortError' ? '已取消' : '请求失败'); });
    renderUploadPanel();
    uploadState.active = false;
    $('upUpload').disabled = false;
    $('upCancel').disabled = true;
  } finally {
    uploadState.controller = null;
  }
}

function cancelUpload() {
  if (uploadState.controller) uploadState.controller.abort();
  uploadState.active = false;
  $('upUpload').disabled = false;
  $('upCancel').disabled = true;
}

// 收集 FileList（文件多选 / 文件夹 webkitdirectory / Drag&Drop），保留相对路径
// source: 'file' 普通文件多选 | 'folder' 文件夹选择器(webkitdirectory) | 'drop' 拖拽（自动推断）
async function handleFileList(fileList, source) {
  const files = Array.from(fileList || []);
  if (!files.length) return;
  const items = [];
  const dirs = new Set();
  let totalSize = 0;
  let ignored = 0;
  for (const f of files) {
    let rel = (f.webkitRelativePath || f.name || '').replace(/\\/g, '/');
    if (!rel) continue;
    if (isUploadIgnored(rel)) { ignored++; continue; }
    if (f.size > MAX_UPLOAD_BYTES) { ignored++; continue; }
    const parts = rel.split('/');
    for (let i = 1; i < parts.length; i++) dirs.add(parts.slice(0, i).join('/'));
    items.push({ rel_path: rel, file: f, size: f.size });
    totalSize += f.size;
  }
  if (!items.length) {
    showToast('没有可上传的文件（全部为空、过大或属于忽略项）');
    return;
  }
  if (items.length > MAX_UPLOAD_FILES) {
    showToast(`文件过多（${items.length} 个 > ${MAX_UPLOAD_FILES}），请分批上传`);
    return;
  }

  // 判定上传形态并提取目标项目名：
  // - 文件夹上传（webkitRelativePath 含共享顶层目录段）→ 新建/切换项目根（顶层段=项目名），写项目内部相对路径
  // - 普通文件上传（无层级）→ 追加写入当前激活项目；未激活时后端建立默认项目 "project"
  let projectName = null;
  let stripTopDir = false;
  if (source === 'folder' || source === 'drop') {
    const hasNested = items.length > 0 && items[0].rel_path.includes('/');
    if (hasNested) {
      const top = items[0].rel_path.split('/')[0];
      const allSame = items.every((it) => it.rel_path.split('/')[0] === top);
      if (allSame) { projectName = top; stripTopDir = true; }
    }
  }
  if (!projectName) projectName = state.projectName; // 文件上传：追加当前激活项目

  openUploadPanel(items, dirs.size, totalSize, ignored, projectName, stripTopDir);
}

// Drag & Drop：支持拖入文件与文件夹（webkitGetAsEntry 递归恢复目录结构）
function collectEntry(entry, base, out) {
  return new Promise((resolve) => {
    if (entry.isFile) {
      entry.file((file) => {
        try { file.webkitRelativePath = (base ? base + '/' : '') + entry.name; } catch (e) { /* ignore */ }
        out.push(file);
        resolve();
      }, () => resolve());
    } else if (entry.isDirectory) {
      const reader = entry.createReader();
      const readBatch = () => {
        reader.readEntries((entries) => {
          if (!entries.length) { resolve(); return; }
          const next = (base ? base + '/' : '') + entry.name;
          Promise.all(entries.map((en) => collectEntry(en, next, out))).then(readBatch);
        }, () => resolve());
      };
      readBatch();
    } else resolve();
  });
}

function setupDragDrop() {
  const zone = $('sideProject');
  if (!zone) return;
  ['dragenter', 'dragover'].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    zone.classList.add('drag-over');
  }));
  ['dragleave', 'drop'].forEach((ev) => zone.addEventListener(ev, (e) => {
    e.preventDefault();
    if (ev === 'dragleave' && zone.contains(e.relatedTarget)) return;
    zone.classList.remove('drag-over');
  }));
  zone.addEventListener('drop', async (e) => {
    zone.classList.remove('drag-over');
    const dt = e.dataTransfer;
    if (!dt) return;
    const collected = [];
    if (dt.items && dt.items.length && typeof dt.items[0].webkitGetAsEntry === 'function') {
      for (const it of dt.items) {
        const entry = it.webkitGetAsEntry();
        if (entry) await collectEntry(entry, '', collected);
      }
    }
    if (collected.length) {
      await handleFileList(collected, 'drop');
      return;
    }
    // fallback：浏览器未提供相对路径（文件夹拖拽不可靠），如实提示
    if (dt.files && dt.files.length) {
      await handleFileList(dt.files, 'drop');
      if (![...dt.files].some((f) => f.webkitRelativePath)) {
        showToast('浏览器未提供文件夹相对路径，内容以顶层文件方式上传');
      }
    }
  });
}

function renderFileTree(tree, container, level = 0) {
  if (level === 0) container.innerHTML = '';
  if (!tree.children) return;
  if (tree.children.length === 0) {
    const hint = level === 0 ? '（空项目，暂无文件）' : '（空目录）';
    container.innerHTML = `<div class="tree-empty" style="padding-left:${level * 12 + 6}px">${hint}</div>`;
    return;
  }
  tree.children.forEach((child) => {
    const item = document.createElement('div');
    const isDirectory = child.type === 'directory';
    const icon = isDirectory
      ? '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M3 7a2 2 0 012-2h4l2 2h8a2 2 0 012 2v8a2 2 0 01-2 2H5a2 2 0 01-2-2V7z"/></svg>'
      : '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M14 2H6a2 2 0 00-2 2v16a2 2 0 002 2h12a2 2 0 002-2V8z"/><path d="M14 2v6h6"/></svg>';
    item.innerHTML = `
      <div class="tree-item" data-path="${esc(child.rel_path || child.name)}" data-type="${child.type}" style="padding-left:${level * 12 + 6}px">
        ${isDirectory ? '<span class="tree-toggle">▶</span>' : '<span class="tree-toggle" style="opacity:0">▶</span>'}
        <span class="tree-item-icon">${icon}</span>
        <span class="tree-item-name">${esc(child.name)}</span>
      </div>
    `;
    container.appendChild(item);
    if (isDirectory) {
      const childrenContainer = document.createElement('div');
      childrenContainer.className = 'tree-children collapsed';
      item.appendChild(childrenContainer);
      const toggle = item.querySelector('.tree-toggle');
      const treeItem = item.querySelector('.tree-item');
      treeItem.addEventListener('click', async () => {
        if (_suppressClick) { _suppressClick = false; return; } // 长按/右键弹出的菜单，吞掉本次 click
        const isCollapsed = childrenContainer.classList.contains('collapsed');
        if (isCollapsed && !childrenContainer.dataset.loaded) {
          try {
            const r = await fetch(`/api/files?path=${encodeURIComponent(child.rel_path || child.name)}`);
            const data = await r.json();
            renderFileTree(data.tree, childrenContainer, level + 1);
            childrenContainer.dataset.loaded = 'true';
            applyTreeStatusBadges();
          } catch (e) {
            childrenContainer.innerHTML = '<div class="tree-empty" style="padding-left:14px">加载失败</div>';
            childrenContainer.dataset.loaded = 'true';
          }
        }
        childrenContainer.classList.toggle('collapsed', !isCollapsed);
        toggle.classList.toggle('open', isCollapsed);
      });
    } else {
      // 文件节点：点击打开真实文件预览（不再是无反应节点）
      const treeItem = item.querySelector('.tree-item');
      treeItem.addEventListener('click', (e) => {
        if (_suppressClick) { _suppressClick = false; e.stopPropagation(); return; } // 长按/右键弹出菜单，吞掉本次 click
        e.stopPropagation();
        openFilePreview(child.rel_path || child.name);
      });
      treeItem.title = child.rel_path || child.name;
    }
    // 长按 / 右键 → 弹出删除菜单（文件与目录统一）
    const treeItem = item.querySelector('.tree-item');
    bindDeleteMenu(treeItem, child.rel_path || child.name, child.type);
  });
  if (level === 0) applyTreeStatusBadges();
}

// ---------- 长按 / 右键删除菜单 ----------
function bindDeleteMenu(el, path, type) {
  const cancelPress = () => { clearTimeout(_pressTimer); _pressTimer = null; };
  el.addEventListener('mousedown', (e) => {
    if (e.button !== 0) return;
    cancelPress();
    _longPressFired = false;
    _pressTimer = setTimeout(() => {
      _pressTimer = null;
      _longPressFired = true;
      _suppressClick = true;
      showDeleteMenu(e.clientX, e.clientY, path, type);
    }, 600); // macOS 长按阈值
  });
  el.addEventListener('mouseup', cancelPress);
  el.addEventListener('mouseleave', cancelPress);
  el.addEventListener('contextmenu', (e) => {
    e.preventDefault(); // 屏蔽系统右键菜单，用自定义菜单替代
    cancelPress();
    _longPressFired = true;
    _suppressClick = true;
    showDeleteMenu(e.clientX, e.clientY, path, type);
  });
}

function showDeleteMenu(x, y, path, type) {
  const menu = $('ctxMenu');
  $('ctxPath').textContent = path;
  $('ctxPath').title = `${type === 'directory' ? '目录' : '文件'}：${path}`;
  const btn = $('ctxDelete');
  btn.dataset.confirm = '0';
  btn.textContent = '删除';
  menu.hidden = false;
  // 定位并 clamp 在视口内
  menu.style.left = '0px';
  menu.style.top = '0px';
  const mw = menu.offsetWidth, mh = menu.offsetHeight;
  menu.style.left = `${Math.max(4, Math.min(x, window.innerWidth - mw - 8))}px`;
  menu.style.top = `${Math.max(4, Math.min(y, window.innerHeight - mh - 8))}px`;
  menu.classList.add('open');
  saveFocus(); // 记录触发元素（文件树节点）
  btn.focus(); // 键盘可达：菜单弹出即聚焦「删除」
}

function closeDeleteMenu() {
  const menu = $('ctxMenu');
  if (menu.hidden) return;
  menu.hidden = true;
  menu.classList.remove('open');
  restoreFocus();
}

function deleteFromMenu() {
  const btn = $('ctxDelete');
  const path = $('ctxPath').textContent;
  if (btn.dataset.confirm !== '1') {
    btn.dataset.confirm = '1';
    btn.textContent = '确认删除？';
    btn.classList.add('danger');
    return; // 一步确认：需再次点击才真正执行
  }
  const body = JSON.stringify({ path });
  fetch('/api/files/delete', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body,
  })
    .then(async (r) => {
      const data = await r.json().catch(() => ({}));
      if (!r.ok || !data.ok) throw new Error(data.detail || `删除失败 (HTTP ${r.status})`);
      closeDeleteMenu();
      showToast(`已删除 ${data.count === 1 ? '' : data.count + ' 项 / '}${data.path}`);
      refreshFileTree();      // 左侧树同步
      loadGitStatus(true);    // Git 状态同步
    })
    .catch((err) => {
      closeDeleteMenu();
      showToast(`删除失败：${err.message}`);
    });
}

// ---------- File preview（真实文件内容，四态：loading/empty/error/success） ----------
let fpLoadToken = 0;

function openFilePreview(path) {
  const overlay = $('filePreview');
  $('fpPath').textContent = path;
  $('fpMeta').textContent = '';
  $('fpBody').innerHTML = '<div class="fp-empty">加载中…</div>';
  overlay.hidden = false;
  saveFocus(); // P3：记录触发元素
  const closeBtn = $('fpClose');
  if (closeBtn) closeBtn.focus(); // P3：focus first element
  // selected state 同步到文件树
  document.querySelectorAll('.tree-item.active').forEach((el) => el.classList.remove('active'));
  const treeEl = document.querySelector(`.tree-item[data-path="${CSS.escape(path)}"]`);
  if (treeEl) treeEl.classList.add('active');

  const token = ++fpLoadToken;
  fetch(`/api/files/content?path=${encodeURIComponent(path)}`, { cache: 'no-store' })
    .then((r) => r.json())
    .then((data) => {
      if (token !== fpLoadToken) return;
      if (!r_ok(data)) throw new Error(data.detail || '加载失败');
      if (!data.ok) {
        $('fpMeta').textContent = formatBytes(data.size || 0);
        $('fpBody').innerHTML = `<div class="fp-error">${esc(data.detail || '无法读取该文件')}</div>`;
        return;
      }
      if (!data.content) {
        $('fpBody').innerHTML = '<div class="fp-empty">（空文件）</div>';
      } else {
        const code = document.createElement('pre');
        code.className = 'fp-code';
        code.textContent = data.content;
        $('fpBody').innerHTML = '';
        $('fpBody').appendChild(code);
      }
      $('fpMeta').textContent = `${data.lines} lines · ${formatBytes(data.size)}`;
    })
    .catch((err) => {
      if (token !== fpLoadToken) return;
      $('fpMeta').textContent = '';
      $('fpBody').innerHTML = `<div class="fp-error">Unable to load file — ${esc(err.message)}</div>`;
    });
}

function r_ok(data) { return data && typeof data === 'object'; }

function formatBytes(n) {
  if (!n && n !== 0) return '';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  return `${(n / 1024 / 1024).toFixed(2)} MB`;
}

function closeFilePreview() {
  fpLoadToken++; // 使进行中的加载失效
  $('filePreview').hidden = true;
  document.querySelectorAll('.tree-item.active').forEach((el) => el.classList.remove('active'));
  restoreFocus(); // P3：恢复触发元素焦点
}

// 项目切换时彻底清理旧项目的全部运行时状态（说明书 §23）。
// 切到 Project B 后，右侧/中心绝不残留 Project A 的 Preview/Git/Diff/Changes/
// Tests/Verification/Timeline/Session。后端 Agent session 由上传接口在激活新项目前
// 触发 _request_cancel_all() 结束，此处只负责前端状态与 DOM 清理。
function clearProjectRuntimeState() {
  closeFilePreview();
  state.activeDiff = null;
  const diffBlock = $('diffBlock');
  if (diffBlock) diffBlock.hidden = true;
  const diffView = $('diffView');
  if (diffView) diffView.textContent = '';
  const diffStats = $('diffStats');
  if (diffStats) diffStats.textContent = '';
  const changeList = $('changeList');
  if (changeList) changeList.innerHTML = '<div class="ctx-muted">No changes</div>';
  const gitCount = $('gitChangedCount');
  if (gitCount) gitCount.textContent = '—';
  const ctxFiles = $('ctxFiles');
  if (ctxFiles) ctxFiles.innerHTML = '<span class="ctx-muted">Agent 操作过的文件将显示在这里</span>';
  const timeline = $('timeline');
  if (timeline) timeline.innerHTML = '';
  const ctxTask = $('ctxTask');
  if (ctxTask) ctxTask.textContent = 'No task running';
  const ctxTime = $('ctxTime');
  if (ctxTime) ctxTime.textContent = '—';
  const checksList = $('checksList');
  if (checksList) checksList.innerHTML = '';
  const checksDetail = $('checksDetail');
  if (checksDetail) checksDetail.textContent = '选择上方的检查项查看输出。';
  const planPanel = $('planPanel');
  if (planPanel) planPanel.hidden = true;
  const planList = $('planList');
  if (planList) planList.innerHTML = '';
  state.filesChanged.clear();
  state.toolsUsed.clear();
  state.planSteps = [];
  state.verification = 'pending';
  state.tests = null;
  state.commands = [];
  state.gitFileStatus = {};
  state.agentState = STATES.IDLE;
  state.agentEnded = true;
  state.lastTask = '';
  updateRunButtonState();
}

function highlightFile(path) {
  document.querySelectorAll('.tree-item.active').forEach((el) => el.classList.remove('active'));
  if (!path) return;
  const el = document.querySelector(`.tree-item[data-path="${CSS.escape(path)}"]`);
  if (el) { el.classList.add('active'); el.scrollIntoView({ behavior: 'smooth', block: 'nearest' }); }
}

// ---------- Git status / Changes / Diff ----------
// P1-10：M/A/D/R/?? 等真实 git 状态映射到稳定 CSS class（颜色/状态视觉真正生效）
function changeStatusClass(st) {
  const map = { M: 'M', A: 'A', D: 'D', R: 'R', '??': 'Q', C: 'C', U: 'U', T: 'T' };
  return map[st] || 'O';
}

async function loadGitStatus(silent = false) {
  try {
    const r = await fetch('/api/git/status', { cache: 'no-store' });
    const data = await r.json();
    // P2-10：null / type check，异常响应不崩 UI
    if (!data || typeof data !== 'object') throw new Error('invalid git status response');
    state.gitChanged = Number(data.changed_count) || 0;
    state.gitStatusLines = Array.isArray(data.changed_files) ? data.changed_files : [];
    state.isGit = data.is_git !== false; // P1-6：非 git 项目 is_git=false，绝不伪造 changed_count
    // 构建 rel_path -> status 映射（真实 git status），供文件树标记 NEW/MODIFIED 等
    state.gitFileStatus = {};
    (state.gitStatusLines || []).forEach((line) => {
      let st = (line.slice(0, 2) || '  ').trim() || '??';
      let path = line.slice(3).trim();
      if (path.startsWith('"') && path.endsWith('"')) {
        try { path = JSON.parse(path); } catch (e) { /* keep raw */ }
      }
      if (!path) return;
      if (st === '??') st = 'NEW';
      state.gitFileStatus[path] = st;
    });
    renderChangeList();
    updateChecks();
    applyTreeStatusBadges();
  } catch (e) {
    if (!silent) {
      $('changeList').innerHTML = '<div class="ctx-muted">git 状态加载失败</div>';
      $('gitChangedCount').textContent = '—';
    }
  }
}

// 文件树状态徽标：把真实 git status 应用到已渲染的文件节点（不伪造）。
// P2-4：状态变化（如 M -> clean）时必须移除旧徽标，不能只加不减。
function applyTreeStatusBadges() {
  document.querySelectorAll('.tree-item[data-type="file"]').forEach((el) => {
    const rel = el.dataset.path;
    const st = state.gitFileStatus[rel];
    const existing = el.querySelector('.tree-badge');
    if (!st) {
      if (existing) existing.remove(); // 状态已变干净 -> 移除旧徽标
      return;
    }
    if (existing && existing.dataset.st === st) return;
    if (existing) existing.remove();
    const badge = document.createElement('span');
    badge.dataset.st = st;
    badge.className = `tree-badge tb-${st === 'NEW' ? 'NEW' : st}`;
    badge.textContent = st === 'NEW' ? 'NEW' : st;
    badge.title = st === 'NEW' ? '未跟踪的新文件' : `git 状态: ${st}`;
    el.appendChild(badge);
  });
}

function renderChangeList() {
  const list = $('changeList');
  if (state.isGit === false) {
    // P1-6：非 Git 项目 —— 明确显示 Unavailable，绝不伪造 "1 file changed"
    $('gitChangedCount').textContent = 'Not a git repo';
    list.innerHTML = '<div class="ctx-muted">Not a Git repository — 不显示伪 Git 状态。</div>';
    $('diffBlock').hidden = true;
    return;
  }
  $('gitChangedCount').textContent = `${state.gitChanged} changed`;
  if (!state.gitStatusLines.length) {
    list.innerHTML = '<div class="ctx-muted">Working tree clean，无未提交改动</div>';
    $('diffBlock').hidden = true;
    return;
  }
  list.innerHTML = state.gitStatusLines
    .map((line, idx) => {
      const st = (line.slice(0, 2) || '  ').trim() || '??';
      const path = line.slice(3).trim();
      const csClass = changeStatusClass(st); // P1-10：M/A/D/R/?? 真正进入对应 CSS class
      return `<div class="change-item" data-idx="${idx}" data-path="${esc(path)}" data-status="${esc(st)}">
        <span class="change-status cs-${csClass}">${esc(st)}</span>
        <span class="change-path">${esc(path)}</span>
      </div>`;
    })
    .join('');
  list.querySelectorAll('.change-item').forEach((el) => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.change-item').forEach((x) => x.classList.remove('active'));
      el.classList.add('active');
      loadDiff(el.dataset.path);
    });
  });
}

async function loadDiff(path) {
  if (state.activeDiff === path) return;
  state.activeDiff = path;
  $('diffBlock').hidden = false;
  $('diffFileName').textContent = path;
  $('diffView').innerHTML = '<span class="diff-empty">加载 diff…</span>';
  $('diffStats').textContent = '';
  try {
    const r = await fetch(`/api/git/diff?path=${encodeURIComponent(path)}`, { cache: 'no-store' });
    const data = await r.json();
    if (!r.ok || !data.ok) {
      $('diffView').innerHTML = `<span class="diff-empty">${esc(data.detail || '无法读取 diff')}</span>`;
      return;
    }
    if (data.detail && !data.diff) {
      $('diffView').innerHTML = `<span class="diff-empty">${esc(data.detail)}</span>`;
      $('diffStats').textContent = data.stats || '';
      return;
    }
    const raw = data.diff || '(无差异内容)';
    const stats = data.stats || '';
    $('diffStats').textContent = stats;
    $('diffView').innerHTML = renderDiff(raw);
  } catch (e) {
    $('diffView').innerHTML = `<span class="diff-empty">加载失败: ${esc(e.message)}</span>`;
  }
}

function renderDiff(raw) {
  return String(raw).split('\n').map((line) => {
    let cls = '';
    if (line.startsWith('+++') || line.startsWith('---') || line.startsWith('diff ') || line.startsWith('index ')) cls = 'd-hunk';
    else if (line.startsWith('@@')) cls = 'd-hunk';
    else if (line.startsWith('+')) cls = 'd-add';
    else if (line.startsWith('-')) cls = 'd-del';
    return `<div class="${cls}">${esc(line) || ' '}</div>`;
  }).join('');
}

// ---------- Sessions ----------
function upsertSession(task, status) {
  state.sessions = state.sessions.filter((s) => s.task !== task);
  state.sessions.unshift({ task, time: nowStr(), status });
  saveSessions();
  renderSessions();
}

function renderSessions() {
  $('sessionCount').textContent = state.sessions.length;
  const list = $('sessionList');
  if (!state.sessions.length) {
    list.innerHTML = '<div class="tree-empty">暂无历史会话</div>';
    return;
  }
  list.innerHTML = state.sessions
    .map((s, idx) => `<div class="session-item" data-idx="${idx}">
      <span class="session-status ${s.status}"></span>
      <span class="session-task">${esc(s.task)}</span>
      <span class="session-time">${esc(s.time)}</span>
    </div>`)
    .join('');
  list.querySelectorAll('.session-item').forEach((el) => {
    el.addEventListener('click', () => {
      const s = state.sessions[Number(el.dataset.idx)];
      if (s) { $('taskInput').value = s.task; autoResizeTextarea(); $('taskInput').focus(); }
    });
  });
}

// ---------- Agent state ----------
function setAgentState(newState, message = '') {
  state.agentState = newState;
  const label = message || STATE_LABEL[newState] || newState;

  const mainBadge = $('mainStateBadge');
  mainBadge.dataset.state = newState;
  mainBadge.querySelector('.state-label').textContent = label;

  const sideBadge = $('sideAgentState');
  sideBadge.dataset.state = newState;
  sideBadge.querySelector('.state-label').textContent = label;

  $('cmdState').dataset.state = newState;
  $('cmdState').textContent = label;

  $('ctxState').dataset.state = newState;
  $('ctxState').querySelector('.ctx-state-label').textContent = label;
  const ctxDot = $('ctxState').querySelector('.state-dot');
  const dotColor = {
    idle: 'var(--text-4)', completed: 'var(--ok)', error: 'var(--err)', cancelled: 'var(--warn)',
    planning: 'var(--accent)', thinking: 'var(--accent)', tool_calling: 'var(--accent)',
    reading: 'var(--accent)', editing: 'var(--accent)', running: 'var(--accent)',
    verifying: 'var(--accent)', repairing: 'var(--warn)',
  }[newState] || 'var(--text-4)';
  ctxDot.style.background = dotColor;

  const isBusy = newState !== STATES.IDLE && newState !== STATES.COMPLETED
    && newState !== STATES.ERROR && newState !== STATES.CANCELLED;
  $('agentCardAvatar').classList.toggle('active', isBusy);
  $('agentCard').classList.toggle('running', isBusy);
}

function inferStateFromTool(tool) {
  if (['read_file', 'search_code', 'list_files'].includes(tool)) return STATES.READING;
  if (['edit_file', 'write_file'].includes(tool)) return STATES.EDITING;
  if (tool === 'git_diff') return STATES.VERIFYING;
  if (tool === 'run_command') return STATES.RUNNING;
  return STATES.TOOL_CALLING;
}

function isVerificationCommand(command) {
  const c = (command || '').toLowerCase();
  return c.includes('pytest') || c.includes('test') || c.includes('verify') || c.includes('check');
}

// ---------- Plan ----------
function planStepLabel(tool, args) {
  const a = args || {};
  const target = a.path || a.command || a.query || a.name || '';
  return `${tool}${target ? '  ' + String(target).slice(0, 42) : ''}`;
}

function addPlanSteps(toolCalls) {
  if (!toolCalls || !toolCalls.length) return;
  toolCalls.forEach((tc) => {
    let args = {};
    try { args = JSON.parse(tc.arguments || '{}'); } catch (e) { /* ignore */ }
    state.planSteps.push({ label: planStepLabel(tc.name, args), state: 'active' });
  });
  renderPlan();
}

function completePlanStep() {
  const idx = state.planSteps.findIndex((s) => s.state === 'active');
  if (idx >= 0) state.planSteps[idx].state = 'done';
  renderPlan();
}

function renderPlan() {
  const panel = $('planPanel');
  const list = $('planList');
  if (!state.planSteps.length) {
    panel.hidden = true;
    list.innerHTML = '';
    $('planCount').textContent = '0 steps';
    return;
  }
  panel.hidden = false;
  const done = state.planSteps.filter((s) => s.state === 'done').length;
  $('planCount').textContent = `${done}/${state.planSteps.length} done`;
  list.innerHTML = state.planSteps
    .map((s, i) => `<div class="plan-step" data-state="${s.state}" data-idx="${i}">
      <span class="plan-dot">${s.state === 'done' ? '✓' : ''}</span>
      <span class="plan-label">${esc(s.label)}</span>
      <span class="plan-meta">${s.state === 'done' ? 'done' : s.state === 'active' ? 'running' : 'queued'}</span>
    </div>`)
    .join('');
}

// ---------- Checks ----------
const CHECK_TEMPLATES = [
  { id: 'verification', name: 'Verification', icon: 'pending', summary: 'Pending', source: 'run_command 输出解析', detail: '尚无验证命令执行。' },
  { id: 'tests', name: 'Tests', icon: 'pending', summary: '—', source: 'pytest 输出解析', detail: '尚未运行测试。' },
  { id: 'git', name: 'Git', icon: 'pending', summary: '—', source: 'git status --short', detail: '加载中…' },
  { id: 'security', name: 'Security', icon: 'pending', summary: 'PLACEHOLDER', source: '未接入', detail: 'SECURITY 检查为 PLACEHOLDER：后端暂无安全扫描接口，仅保留 UI 骨架，不伪造结果。' },
];
const checksState = {
  verification: { icon: 'pending', summary: 'Pending', detail: '尚无验证命令执行。' },
  tests: { icon: 'pending', summary: '—', detail: '尚未运行测试。' },
  git: { icon: 'pending', summary: '—', detail: '加载中…' },
  security: { icon: 'pending', summary: 'PLACEHOLDER', detail: 'SECURITY 检查为 PLACEHOLDER：后端暂无安全扫描接口，仅保留 UI 骨架，不伪造结果。' },
};

function renderChecks() {
  const list = $('checksList');
  list.innerHTML = CHECK_TEMPLATES.map((t) => {
    const c = checksState[t.id];
    return `<div class="check-card" data-check="${t.id}">
      <div class="check-card-head">
        <span class="check-icon ${c.icon}">${c.icon === 'ok' ? '✓' : c.icon === 'err' ? '✕' : c.icon === 'warn' ? '!' : '·'}</span>
        <span class="check-name">${t.name}${t.id === 'security' ? '<span class="ph-badge">PLACEHOLDER</span>' : ''}</span>
        <span class="check-summary">${esc(c.summary)}</span>
      </div>
      <div class="check-source">来源：${esc(t.source)}</div>
    </div>`;
  }).join('');
  list.querySelectorAll('.check-card').forEach((el) => {
    el.addEventListener('click', () => {
      list.querySelectorAll('.check-card').forEach((x) => x.classList.remove('active'));
      el.classList.add('active');
      $('checksDetail').textContent = checksState[el.dataset.check].detail || '（无输出）';
    });
  });
}

function updateChecks() {
  // Git（真实状态：is_git=false 时显示 Not a Git repository，绝不伪造 changed_count）
  if (state.isGit === false) {
    checksState.git.summary = 'Not a Git repository';
    checksState.git.icon = 'warn';
    checksState.git.detail = '当前项目不含 .git，不显示伪 Git 状态。';
  } else {
    checksState.git.summary = `${state.gitChanged} files changed`;
    checksState.git.icon = state.gitChanged > 0 ? 'warn' : 'ok';
    checksState.git.detail = state.gitStatusLines.length
      ? state.gitStatusLines.join('\n')
      : 'Working tree clean。';
  }
  renderChecks();
}

function noteVerification(exitCode) {
  checksState.verification.icon = exitCode === 0 ? 'ok' : 'err';
  checksState.verification.summary = exitCode === 0 ? 'Passed' : 'Failed';
  checksState.verification.detail = `验证命令 exit code = ${exitCode}\n（源自 run_command 输出解析，真实数据）`;
  renderChecks();
}

function noteTestResult(text) {
  const s = String(text || '');
  const passed = s.match(/(\d+)\s+passed/);
  const failed = s.match(/(\d+)\s+failed/);
  if (passed || failed) {
    const p = passed ? parseInt(passed[1], 10) : 0;
    const f = failed ? parseInt(failed[1], 10) : 0;
    checksState.tests.icon = f > 0 ? 'err' : 'ok';
    checksState.tests.summary = `${p} passed${f ? `, ${f} failed` : ''}`;
    checksState.tests.detail = truncateOutput(s, 3000);
    renderChecks();
  }
}

// ---------- Run reset / finish ----------
function resetRun() {
  state.currentTurn = 0;
  state.toolCounter = 0;
  state.pendingToolNodeId = null;
  state.planSteps = [];
  state.toolsUsed = new Map();
  state.filesChanged = new Map();
  state.commands = [];
  state.verification = 'pending';
  state.logPath = null;
  state.startTime = Date.now();
  startTimer(); // P2-8：运行启动即计时；完成/停止时由 finishRun 停止并清零
  $('timeline').innerHTML = '';
  $('welcome').classList.add('hidden');
  renderPlan();
  setAgentState(STATES.PLANNING, 'Planning');
  $('topTaskName').textContent = state.task;
  $('topTaskTitle').title = state.task;
  $('ctxTask').textContent = state.task;
  $('ctxTime').textContent = `Started at ${nowStr()}`;
  updateRunButtonState(); // busy -> Stop 可点
  $('stopBtn').disabled = false;
  $('pauseBtn').disabled = false;
  upsertSession(state.task, 'running');
}

function finishRun() {
  updateRunButtonState(); // 恢复 Run（空输入禁用）
  $('stopBtn').disabled = true;
  $('pauseBtn').disabled = true;
  $('stopBtn').classList.remove('stopping'); // P1-4/5：取消停止态
  $('stopBtn').title = '停止当前运行';
  $('agentCardAvatar').classList.remove('active');
  $('agentCard').classList.remove('running');
  saveRecent(state.task);
  stopTimer();           // P2-8：完成/停止后停止计时，不再于 Idle 继续增长
  state.startTime = null;
  // 运行结束后刷新真实 git 状态与文件树（四区联动）
  refreshFileTree();
  loadGitStatus(true);
}

// ---------- Timeline ----------
function getOrCreateTurnNode(turn, type) {
  let node = document.getElementById(`turn-${turn}-${type}`);
  if (node) return node;
  const wrapper = document.createElement('div');
  wrapper.className = `timeline-node node-type-${type}`;
  wrapper.id = `turn-${turn}-${type}`;
  const titleMap = {
    user: 'Task', thinking: 'Thinking', reading: 'Reading', editing: 'Editing',
    running: 'Running', verifying: 'Verifying', repairing: 'Repairing',
    completed: 'Completed', error: 'Error',
  };
  wrapper.innerHTML = `
    <div class="node-rail">
      <div class="node-dot"></div>
      <div class="node-line"></div>
    </div>
    <div class="node-content">
      <div class="node-header">
        <div class="node-icon">${ICONS[type] || '<span style="color:var(--text-3)">●</span>'}</div>
        <div class="node-title">${titleMap[type] || type}</div>
        <div class="node-subtitle"></div>
        <div class="node-toggle">▶</div>
      </div>
      <div class="node-body"></div>
    </div>
  `;
  wrapper.querySelector('.node-header').addEventListener('click', () => {
    wrapper.querySelector('.node-content').classList.toggle('open');
  });
  $('timeline').appendChild(wrapper);
  maybeCollapseOldNodes();
  return wrapper;
}

function maybeCollapseOldNodes() {
  const timeline = $('timeline');
  const nodes = Array.from(timeline.children).filter((el) => el.classList.contains('timeline-node'));
  if (nodes.length <= MAX_VISIBLE_NODES) {
    timeline.querySelectorAll('.old-activity-summary').forEach((el) => el.remove());
    nodes.forEach((el) => el.classList.remove('old-collapsed'));
    return;
  }
  nodes.slice(0, nodes.length - MAX_VISIBLE_NODES).forEach((el) => el.classList.add('old-collapsed'));
  nodes.slice(nodes.length - MAX_VISIBLE_NODES).forEach((el) => el.classList.remove('old-collapsed'));
  let summary = timeline.querySelector('.old-activity-summary');
  const hiddenCount = timeline.querySelectorAll('.timeline-node.old-collapsed').length;
  if (!summary) {
    summary = document.createElement('button');
    summary.className = 'old-activity-summary';
    summary.textContent = `Earlier activity · ${hiddenCount} turns`;
    summary.addEventListener('click', () => {
      timeline.querySelectorAll('.timeline-node.old-collapsed').forEach((el) => el.classList.remove('old-collapsed'));
      summary.remove();
    });
    timeline.insertBefore(summary, timeline.firstChild);
  } else {
    summary.textContent = `Earlier activity · ${hiddenCount} turns`;
  }
}

function addUserTaskNode(task) {
  const node = getOrCreateTurnNode(0, 'user');
  node.querySelector('.node-subtitle').textContent = task;
  node.querySelector('.node-body').innerHTML = `
    <div class="node-section">
      <div class="node-section-label">Task</div>
      <div class="node-pre">${esc(task)}</div>
    </div>
  `;
  node.querySelector('.node-content').classList.add('open');
}

function updateThinkingNode(turn, reasoning, content, toolCalls) {
  const node = getOrCreateTurnNode(turn, 'thinking');
  const subtitle = reasoning ? reasoning.split('\n')[0].slice(0, 80)
    : (content ? content.slice(0, 80) : 'Processing...');
  node.querySelector('.node-subtitle').textContent = subtitle;
  let html = '';
  if (reasoning) html += `<div class="node-section"><div class="node-section-label">Reasoning</div><div class="node-pre">${esc(reasoning)}</div></div>`;
  if (content) html += `<div class="node-section"><div class="node-section-label">Response</div><div class="node-pre">${esc(content)}</div></div>`;
  if (toolCalls && toolCalls.length) {
    html += `<div class="node-section"><div class="node-section-label">Planned Tools</div>` +
      toolCalls.map((tc) => `<div class="node-tool-name" style="cursor:default">${ICONS[tc.name] || '●'} ${esc(tc.name)}</div>`).join('') +
      `</div>`;
  }
  node.querySelector('.node-body').innerHTML = html;
}

function addToolStartNode(turn, tool, args, toolCallId) {
  state.toolCounter += 1;
  const type = inferStateFromTool(tool);
  const node = getOrCreateTurnNode(turn, type);
  const shortArg = (args.path || args.command || tool).slice(0, 40);
  node.querySelector('.node-subtitle').textContent = shortArg;
  const body = node.querySelector('.node-body');
  const key = toolCallId || `seq-${state.toolCounter}`;   // P2-2：优先后端 tool_call_id
  const toolId = `tool-${key}`;
  state.pendingToolNodeId = toolId;
  const toolNode = document.createElement('div');
  toolNode.className = 'node-tool tool-running';
  toolNode.id = toolId;
  toolNode.dataset.toolCallId = key;
  toolNode.dataset.status = 'RUNNING'; // P2-2：PENDING -> RUNNING -> SUCCESS/ERROR 状态关联
  toolNode.dataset.path = args.path || '';
  toolNode.dataset.command = args.command || '';
  toolNode.innerHTML = `
    <div class="node-tool-name">
      <span style="color:var(--text-3)">${ICONS[tool] || '●'}</span>
      <span>${esc(tool)}</span>
      <span class="tool-running">●</span>
    </div>
    <div class="node-tool-args">${esc(JSON.stringify(args, null, 2))}</div>
    <div class="node-tool-output"></div>
  `;
  toolNode.querySelector('.node-tool-name').addEventListener('click', () => {
    toolNode.classList.toggle('open');
  });
  body.appendChild(toolNode);
  state.toolNodes.set(key, toolNode); // P2-2：按 tool_call_id 关联状态
  // 当前活跃 Tool 所在节点自动展开，让用户实时看到 Agent 动作；其余节点保持折叠
  const contentEl = node.querySelector('.node-content');
  if (contentEl) contentEl.classList.add('open');
}

function addToolEndNode(turn, tool, output, success, toolCallId) {
  // P2-2：按 tool_call_id（或可靠的顺序 id）关联 start/end，避免并行工具状态错标
  const key = toolCallId || (state.pendingToolNodeId ? state.pendingToolNodeId.replace(/^tool-/, '') : null);
  const toolNode = key ? (document.getElementById(`tool-${key}`) || state.toolNodes.get(key) || null) : null;
  if (!toolNode) return;
  toolNode.classList.remove('tool-running');
  toolNode.classList.add(success ? 'tool-success' : 'tool-error');
  toolNode.dataset.status = success ? 'SUCCESS' : 'ERROR';
  const nameEl = toolNode.querySelector('.node-tool-name');
  nameEl.innerHTML = `
    <span style="color:${success ? 'var(--ok)' : 'var(--err)'}">${ICONS[tool] || '●'}</span>
    <span>${esc(tool)}</span>
    <span style="color:${success ? 'var(--ok)' : 'var(--err)'}">${success ? '✓' : '✕'}</span>
  `;
  const outEl = toolNode.querySelector('.node-tool-output');
  const display = truncateOutput(output);
  outEl.className = 'node-tool-output ' + (success ? 'success' : 'error');
  outEl.textContent = display;
  if (String(output).length > MAX_OUTPUT_LEN) {
    outEl.title = '点击展开完整输出';
    outEl.style.cursor = 'pointer';
    outEl.addEventListener('click', function expand(e) {
      e.stopPropagation();
      outEl.textContent = output;
      outEl.style.cursor = 'default';
      outEl.title = '';
      outEl.removeEventListener('click', expand);
    });
  }

  // 捕获文件修改（真实）
  const path = toolNode.dataset.path;
  if ((tool === 'edit_file' || tool === 'write_file') && path) {
    state.filesChanged.set(path, { tool, time: Date.now() });
    renderCtxFiles();
    highlightFile(path);
  }
  if ((tool === 'read_file') && path) highlightFile(path);

  // 命令与验证（真实）
  if (tool === 'run_command') {
    const command = toolNode.dataset.command || '';
    const match = output.match(/exit_code=(\d+)/);
    const exitCode = match ? parseInt(match[1], 10) : (success ? 0 : 1);
    state.commands.push({ command, exitCode });
    if (isVerificationCommand(command)) {
      state.verification = exitCode === 0 ? 'pass' : 'fail';
      noteVerification(exitCode);
      // 解析测试结果
      const testMatch = output.match(/(\d+)\s+passed/);
      const failMatch = output.match(/(\d+)\s+failed/);
      if (testMatch || failMatch) noteTestResult(output);
    }
  }
  state.toolNodes.delete(key); // P2-2：清理已完成的 tool 关联
  completePlanStep();
}

function renderCtxFiles() {
  const box = $('ctxFiles');
  if (!state.filesChanged.size) {
    box.innerHTML = '<span class="ctx-muted">Agent 操作过的文件将显示在这里</span>';
    return;
  }
  box.innerHTML = Array.from(state.filesChanged.keys())
    .map((p) => `<div class="ctx-file"><span class="file-status">✓</span>${esc(p)}</div>`)
    .join('');
}

function addRepairNode(turn, attempt, maxRepairs) {
  const node = getOrCreateTurnNode(turn, 'repairing');
  node.querySelector('.node-subtitle').textContent = `Attempt ${attempt}/${maxRepairs}`;
  node.querySelector('.node-body').innerHTML = `
    <div class="node-section"><div class="node-pre">Agent detected a failure and is repairing. Attempt ${attempt} of ${maxRepairs}.</div></div>
  `;
  // 修复节点默认展开提示（当前动作）
  node.querySelector('.node-content').classList.add('open');
}

function addCompletedNode(finalAnswer) {
  const node = getOrCreateTurnNode(99, 'completed');
  node.querySelector('.node-subtitle').textContent = 'Task finished';
  node.querySelector('.node-body').innerHTML = `
    <div class="node-section"><div class="node-section-label">Final Answer</div><div class="node-pre">${esc(finalAnswer)}</div></div>
  `;
  node.querySelector('.node-content').classList.add('open');
  upsertSession(state.task, 'done');
}

function addErrorNode(error, stoppedBy) {
  const node = getOrCreateTurnNode(99, 'error');
  node.querySelector('.node-subtitle').textContent = stoppedBy;
  node.querySelector('.node-body').innerHTML = `
    <div class="node-section"><div class="node-section-label">What happened</div><div class="node-pre">${esc(error)}</div></div>
  `;
  node.querySelector('.node-content').classList.add('open');
  upsertSession(state.task, 'error');
}

function addStatusMessage(text, type = '') {
  const msg = document.createElement('div');
  msg.className = `status-message ${type}`;
  msg.textContent = text;
  $('timeline').appendChild(msg);
  scrollToBottom();
}

function scrollToBottom() {
  const sc = $('workspaceScroll');
  sc.scrollTop = sc.scrollHeight;
}

// ---------- SSE Run ----------
// P1-4/5：Stop —— 前端取消 -> 后端 cancellation -> Agent loop 检测取消 -> 停止执行 -> 后端 Emit CANCELLED
async function stopAgent() {
  if (state.agentEnded) return;
  state.cancelling = true;
  $('stopBtn').classList.add('stopping');
  $('stopBtn').title = '正在停止…';
  try {
    // 先通知后端请求取消（cancellation glue），让 Agent loop 停止并回 CANCELLED
    await fetch('/api/agent/cancel', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({}),
    });
  } catch (e) { /* 后端离线：仍中止前端 SSE，后端恢复后任务独立结束 */ }
  if (state.abortController) state.abortController.abort();
  addStatusMessage('已请求取消运行，等待后端停止…', '');
}

async function runAgent(task) {
  state.task = task;
  state.lastTask = task;
  state.cancelling = false;
  state.agentEnded = false;
  resetRun();
  addUserTaskNode(task);
  state.abortController = new AbortController();

  try {
    const response = await fetch('/v1/agent/run/stream', {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ task }),
      signal: state.abortController.signal,
    });
    if (!response.ok || !response.body) throw new Error(`HTTP ${response.status}`);
    const reader = response.body.getReader();
    const decoder = new TextDecoder();
    let buffer = '';
    while (true) {
      const { done, value } = await reader.read();
      if (done) break;
      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split('\n\n');
      buffer = lines.pop() || '';
      for (const chunk of lines) {
        const trimmed = chunk.trim();
        if (!trimmed.startsWith('data:')) continue;
        try {
          const parsed = JSON.parse(trimmed.slice(5).trim());
          if (!parsed || typeof parsed !== 'object') continue; // P2-10
          if (parsed.event === 'complete' || parsed.event === 'error' || parsed.event === 'cancelled') state.agentEnded = true;
          handleEvent(parsed.event, parsed.data);
        } catch (e) { /* ignore malformed */ }
      }
    }
  } catch (e) {
    if (e.name === 'AbortError') {
      // P1-4/5：Stop 已先向后端发取消请求；若后端未在流关闭前送达 cancelled 事件，此处兜底显示 CANCELLED
      if (state.cancelling) {
        addStatusMessage('已停止接收输出（后端停止执行）', '');
        setAgentState(STATES.CANCELLED, 'Stopped');
        upsertSession(state.task, 'cancelled');
      } else {
        addStatusMessage('已停止接收运行输出', '');
        setAgentState(STATES.IDLE, 'Stopped');
        upsertSession(state.task, 'error');
      }
    } else {
      addStatusMessage(`Connection failed: ${e.message}`, 'error');
      setAgentState(STATES.ERROR, 'Connection failed');
      upsertSession(state.task, 'error');
      // SSE 中断：显示 Connection interrupted，并提供 Retry（重跑当前任务）
      const retryTask = state.lastTask;
      showBanner('Connection interrupted', 'err', '与后端流式连接中断，可重试。', true, () => {
        hideBanner();
        if (retryTask) runAgent(retryTask);
      });
    }
  } finally {
    finishRun();
  }
}

function handleEvent(event, data) {
  // P2-10：SSE payload null / type check，异常事件不崩 UI
  if (!data || typeof data !== 'object') {
    if (event === 'complete' || event === 'error' || event === 'cancelled') {
      setAgentState(
        event === 'error' ? STATES.ERROR : event === 'cancelled' ? STATES.CANCELLED : STATES.COMPLETED,
        event
      );
    }
    scrollToBottom();
    return;
  }
  switch (event) {
    case 'thinking': {
      state.currentTurn = Number(data.turn) || state.currentTurn;
      setAgentState(STATES.THINKING, `Thinking · Turn ${state.currentTurn}`);
      updateThinkingNode(state.currentTurn, data.reasoning, data.content, data.tool_calls);
      if (data.tool_calls) {
        addPlanSteps(data.tool_calls);
        data.tool_calls.forEach((tc) => state.toolsUsed.set(tc.name, { status: 'pending' }));
      }
      $('mainTurnCounter').textContent = `turn ${state.currentTurn}`;
      $('sideTurnCounter').textContent = `turn ${state.currentTurn}`;
      break;
    }
    case 'tool_start': {
      const tState = inferStateFromTool(data.tool);
      setAgentState(tState, `${STATE_LABEL[tState]} · Turn ${data.turn}`);
      state.toolsUsed.set(data.tool, { status: 'running' });
      addToolStartNode(data.turn, data.tool, data.arguments || {}, data.tool_call_id);
      break;
    }
    case 'tool_end': {
      state.toolsUsed.set(data.tool, { status: data.success ? 'done' : 'failed' });
      addToolEndNode(data.turn, data.tool, data.output, data.success, data.tool_call_id);
      if (!data.success) setAgentState(STATES.REPAIRING, 'Repairing');
      break;
    }
    case 'turn_complete': {
      if (data.any_failure) setAgentState(STATES.REPAIRING, 'Analyzing failure');
      else setAgentState(STATES.THINKING, 'Thinking');
      break;
    }
    case 'repair': {
      setAgentState(STATES.REPAIRING, `Repair ${data.attempt}/${data.max_repairs}`);
      addRepairNode(data.turn, data.attempt, data.max_repairs);
      break;
    }
    case 'cancelled': {
      // P1-4/5：后端确认取消 -> CANCELLED 终态（真实事件，非伪造）
      state.logPath = data.log_path;
      setAgentState(STATES.CANCELLED, 'Cancelled');
      addStatusMessage(data.error || 'Run cancelled by user. 已停止执行，未继续修改文件。', '');
      $('envLog').textContent = data.log_path || '—';
      upsertSession(state.task, 'cancelled');
      break;
    }
    case 'complete': {
      state.logPath = data.log_path;
      setAgentState(STATES.COMPLETED, 'Completed');
      addCompletedNode(data.final_answer);
      if (data.trace && data.trace.length) state.turns = data.trace;
      $('envLog').textContent = data.log_path || '—';
      hideBanner();
      break; // P2-9：文件树/git 刷新统一由 finishRun 在 finally 完成，避免重复刷新
    }
    case 'error': {
      state.logPath = data.log_path;
      setAgentState(STATES.ERROR, 'Error');
      addErrorNode(data.error || 'Unknown error', data.stopped_by || 'error');
      $('envLog').textContent = data.log_path || '—';
      break; // P2-9：刷新统一由 finishRun 完成
    }
  }
  scrollToBottom();
}

// ---------- Elapsed timer ----------
let timerHandle = null;
function startTimer() {
  stopTimer();
  timerHandle = setInterval(() => {
    if (!state.startTime) return;
    const elapsed = formatTime(Date.now() - state.startTime);
    $('mainElapsed').textContent = elapsed;
    $('sideElapsed').textContent = elapsed;
    $('ctxTime').textContent = `Elapsed ${elapsed} · started ${nowStr()}`;
  }, 1000);
}
function stopTimer() { if (timerHandle) clearInterval(timerHandle); timerHandle = null; }

// ---------- Responsive: side / context drawers ----------
function initDrawers() {
  const contextToggle = document.createElement('button');
  contextToggle.className = 'icon-btn context-toggle';
  contextToggle.id = 'contextToggle';
  contextToggle.title = '切换 Context 面板';
  contextToggle.innerHTML = '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M4 6h16M4 12h16M4 18h10"/></svg>';
  $('newTaskBtn').insertAdjacentElement('afterend', contextToggle);
  contextToggle.addEventListener('click', () => $('contextPanel').classList.toggle('open'));

  $('sidebarCollapse').addEventListener('click', () => {
    const sb = $('sidebar');
    if (window.innerWidth <= 860) sb.classList.toggle('open');
    else sb.classList.toggle('collapsed');
  });

  window.addEventListener('resize', debounce(() => {
    if (window.innerWidth > 1100) $('contextPanel').classList.remove('open');
    if (window.innerWidth > 860) $('sidebar').classList.remove('open');
  }, 150));
}

function debounce(fn, ms) {
  let t; return (...a) => { clearTimeout(t); t = setTimeout(() => fn(...a), ms); };
}

// ---------- Textarea ----------
function autoResizeTextarea() {
  const ta = $('taskInput');
  ta.style.height = 'auto';
  ta.style.height = clamp(ta.scrollHeight, 40, 140) + 'px';
}

// ---------- Init ----------
function updateRunButtonState() {
  const busy = state.agentState !== STATES.IDLE
    && state.agentState !== STATES.COMPLETED
    && state.agentState !== STATES.ERROR
    && state.agentState !== STATES.CANCELLED;
  if (busy) {
    $('runBtn').disabled = false;
    $('runBtn').querySelector('.run-text').textContent = 'Stop';
    return;
  }
  const hasText = $('taskInput').value.trim().length > 0;
  // P1-9：未加载 Project 时 Run 禁用（点击提示先 Open a project）
  const canRun = hasText && !!state.projectRoot;
  $('runBtn').disabled = !canRun;
  $('runBtn').title = !state.projectRoot ? 'Open a project first' : '';
  $('runBtn').querySelector('.run-text').textContent = 'Run';
}

// 浏览器刷新恢复（说明书 §25）：重新拉取 Active Project / Agent Status / File Tree / Git Status。
// 若后端显示 Agent 仍在运行，UI 明确显示 "Agent session active / Reconnecting..."，
// 并提供 Stop 让用户主动结束后端运行中的 session；绝不假装恢复不存在的 SSE 数据。
async function fetchAgentStatus() {
  try {
    const r = await fetch('/api/agent/status', { cache: 'no-store' });
    const data = await r.json();
    if (data && data.running) {
      showBanner('Agent session active', 'info', 'Reconnecting...（SSE 已断开，可点 Stop 结束运行）', true, () => stopAgent());
      state.agentState = STATES.RUNNING;
      state.agentEnded = false;
      state.cancelling = false;
      const stopBtn = $('stopBtn');
      if (stopBtn) stopBtn.disabled = false;
      updateRunButtonState();
    }
    // File Tree / Git Status 的正常恢复由 init() 中的 loadFileTree / loadGitStatus 完成
  } catch (e) {
    // backend unavailable：由 checkHealth / 全局 banner 处理，不在此处伪造状态
  }
}

function init() {
  checkHealth();
  fetchAgentStatus(); // 刷新恢复：检测是否有仍运行的 Agent session（真实后端状态）
  // P1-3：periodic heartbeat（30s），断开可转 Offline、恢复可回 Connected
  healthTimer = setInterval(() => checkHealth(), 30000);
  renderChecks();
  renderSessions();
  loadFileTree('.');
  loadGitStatus(true);
  renderChangeList();
  initDrawers();
  updateRunButtonState();

  $('runBtn').addEventListener('click', () => {
    const busy = state.agentState !== STATES.IDLE
      && state.agentState !== STATES.COMPLETED
      && state.agentState !== STATES.ERROR
      && state.agentState !== STATES.CANCELLED;
    if (busy) {
      // 运行中：Run 按钮即 Stop，真实请求后端取消（P1-4/5）
      stopAgent();
      return;
    }
    const task = $('taskInput').value.trim();
    if (!task) { showToast('请输入任务描述'); return; }
    // P1-9：未加载 Project 禁止 Run
    if (!state.projectRoot) {
      showBanner('Open a project first', 'warn', '运行前请先上传/打开一个项目文件夹，Agent 才能真实读写文件。', false, null);
      return;
    }
    runAgent(task);
  });

  $('taskInput').addEventListener('keydown', (e) => {
    // Enter 运行 / Shift+Enter 换行 / Cmd(Ctrl)+Enter 运行
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) {
      e.preventDefault();
      if ($('runBtn').disabled) return;
      $('runBtn').click();
    }
  });
  $('taskInput').addEventListener('input', () => {
    autoResizeTextarea();
    updateRunButtonState();
  });

  // Esc 关闭：删除菜单优先；其次 Open Project 选择弹层；再次上传面板（非上传中）；再次文件预览 modal；最后收起已展开的 Context drawer
  document.addEventListener('keydown', (e) => {
    if (e.key === 'Escape') {
      if (!$('ctxMenu').hidden) { closeDeleteMenu(); return; }
      const op = $('openProjectModal');
      if (!op.hidden) { closeProjectModal(); return; }
      const um = $('uploadModal');
      if (!um.hidden && !uploadState.active) { closeUploadPanel(); return; }
      const fp = $('filePreview');
      if (!fp.hidden) { closeFilePreview(); return; }
      if (window.innerWidth <= 1100 && $('contextPanel').classList.contains('open')) {
        $('contextPanel').classList.remove('open');
      }
    }
  });

  $('newTaskBtn').addEventListener('click', () => {
    $('taskInput').value = '';
    $('taskInput').focus();
    autoResizeTextarea();
    updateRunButtonState();
  });
  // search/attach/context 均为 disabled 的 Coming soon，不再挂假交互
  $('bannerClose').addEventListener('click', () => hideBanner());

  // Stop = 前端取消 -> 后端 cancellation -> Agent loop 停止（P1-4/5）
  $('stopBtn').addEventListener('click', () => stopAgent());
  $('pauseBtn').addEventListener('click', () => showToast('Pause（即将推出）'));

  // Upload（文件 / 文件夹 → Project Root，保留相对路径）
  $('uploadBtn').addEventListener('click', () => $('fileInput').click());
  $('folderBtn').addEventListener('click', () => $('folderInput').click());
  $('fileInput').addEventListener('change', (e) => { handleFileList(e.target.files, 'file'); e.target.value = ''; });
  $('folderInput').addEventListener('change', (e) => { handleFileList(e.target.files, 'folder'); e.target.value = ''; });
  $('upUpload').addEventListener('click', () => startUpload());
  $('upCancel').addEventListener('click', () => cancelUpload());
  $('upClose').addEventListener('click', () => closeUploadPanel());
  $('upReplace').addEventListener('click', () => { uploadState.conflictMode = 'replace'; $('upConflict').hidden = true; startUpload(); });
  $('upSkip').addEventListener('click', () => { uploadState.conflictMode = 'skip'; $('upConflict').hidden = true; startUpload(); });
  $('upCancelConflict').addEventListener('click', () => { uploadState.active = false; closeUploadPanel(); showToast('已取消上传'); });
  $('uploadModal').addEventListener('click', (e) => { if (e.target === $('uploadModal') && !uploadState.active) closeUploadPanel(); });
  setupDragDrop();

  // File preview modal 关闭 / 复制
  $('fpClose').addEventListener('click', () => closeFilePreview());
  $('filePreview').addEventListener('click', (e) => {
    if (e.target === $('filePreview')) closeFilePreview();
  });
  $('fpCopy').addEventListener('click', async () => {
    const text = $('fpBody').textContent || '';
    try {
      await navigator.clipboard.writeText(text);
      showToast('内容已复制到剪贴板');
    } catch (err) {
      showToast('复制失败（浏览器权限受限）');
    }
  });

  // Welcome quick actions
  // Open Project 选择弹层：打开 / 关闭（复用 upload-overlay 视觉，不重造上传系统）
  function openProjectModal() {
    // 显示当前激活项目根目录（真实数据，来自 projectBadge.title 或 envProject）
    $('opRootPath').textContent = $('projectBadge').title || $('envProject').textContent || '（项目未加载）';
    saveFocus(); // P3
    $('openProjectModal').hidden = false;
    const first = $('opClose');
    if (first) first.focus(); // P3：focus first element
  }
  function closeProjectModal() {
    $('openProjectModal').hidden = true;
    restoreFocus(); // P3
  }
  $('openProjectAction').addEventListener('click', () => {
    // 直接打开系统文件夹选择器（webkitdirectory 上传链路，建/切 Project Root 三端同源），跳过二选一弹窗
    $('folderInput').click();
  });
  // 弹层选项：文件夹 → 系统文件夹选择器（webkitdirectory 上传链路，建/切 Project Root 三端同源）
  $('opFolder').addEventListener('click', () => {
    closeProjectModal();
    $('folderInput').click();
  });
  // 弹层选项：文件 → 系统文件选择器（fileInput 上传链路，真实导入当前/默认项目）
  $('opFile').addEventListener('click', () => {
    closeProjectModal();
    $('fileInput').click();
  });
  $('opClose').addEventListener('click', () => closeProjectModal());
  $('openProjectModal').addEventListener('click', (e) => {
    if (e.target === $('openProjectModal')) closeProjectModal();
  });
  $('recentAction').addEventListener('click', () => {
    const first = state.sessions[0];
    if (first) { $('taskInput').value = first.task; autoResizeTextarea(); $('taskInput').focus(); }
    else showToast('暂无历史会话');
  });
  // 欢迎页 New Task 快捷按钮：清空任务输入框并聚焦（与右上角 newTaskBtn 行为一致），不预填任何示例
  const welcomeNewTask = $('welcomeNewTaskAction');
  if (welcomeNewTask) {
    welcomeNewTask.addEventListener('click', () => {
      $('taskInput').value = '';
      $('taskInput').focus();
      autoResizeTextarea();
      updateRunButtonState();
    });
  }

  // Context tabs（P3：aria-selected / aria-controls）
  document.querySelectorAll('.context-tab').forEach((tab) => {
    tab.setAttribute('role', 'tab');
    if (!tab.hasAttribute('aria-selected')) tab.setAttribute('aria-selected', String(tab.classList.contains('active')));
    if (!tab.hasAttribute('aria-controls')) tab.setAttribute('aria-controls', `view-${tab.dataset.tab}`);
    tab.addEventListener('click', () => {
      document.querySelectorAll('.context-tab').forEach((t) => { t.classList.remove('active'); t.setAttribute('aria-selected', 'false'); });
      document.querySelectorAll('.context-view').forEach((v) => v.classList.remove('active'));
      tab.classList.add('active');
      tab.setAttribute('aria-selected', 'true');
      const v = document.getElementById(`view-${tab.dataset.tab}`);
      if (v) v.classList.add('active');
    });
  });

  // Git refresh / diff close
  $('gitRefresh').addEventListener('click', () => { loadGitStatus(true); });
  $('diffClose').addEventListener('click', () => { $('diffBlock').hidden = true; state.activeDiff = null; });

  // 删除菜单：按钮两步确认执行；点击菜单外 / 滚动 / 缩放关闭
  $('ctxDelete').addEventListener('click', (e) => { e.stopPropagation(); deleteFromMenu(); });
  document.addEventListener('mousedown', (e) => {
    const menu = $('ctxMenu');
    if (!menu.hidden && !menu.contains(e.target)) closeDeleteMenu();
  });
  window.addEventListener('resize', () => closeDeleteMenu());
  document.querySelector('.app-body')?.addEventListener('scroll', () => closeDeleteMenu(), true);
}

init();
