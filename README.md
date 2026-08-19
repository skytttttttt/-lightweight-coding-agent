# V4-Flash Coding Agent

运行于 macOS + Python 的自主 Coding Agent，核心模型 **DeepSeek V4-Flash**。
用户输入编程任务后，Agent 自动完成：检查项目 → 搜索代码 → 读取文件 → 制定修改方案 → 修改代码 → 运行测试 → 分析失败 → 自动修复（最多 2 次）→ 重新验证 → 检查 Git Diff → 输出最终结果。

## 功能特性

- **6 个工具**：`list_files` / `read_file` / `search_code` / `edit_file` / `run_command` / `git_diff`
- **Sandbox 安全沙箱**：所有文件操作限制在 `workspace/` 内，拒绝 `../../` 路径逃逸
- **Agent Loop**：最大 30 turns，完整保留每轮 `reasoning_content`（Thinking）与 `tool_calls`
- **Repair 协议**：同一问题最多自动修复 2 次，连续失败自动停止
- **GOALS 协议**：修改 2 个及以上文件时先输出计划
- **CLI 与 API 双入口**

## 项目结构

```
v4-flash-agent/
├── app/
│   ├── main.py            # CLI 入口 (python -m app.main "任务")
│   ├── config.py          # 配置加载 (.env)
│   ├── server.py          # API Server (FastAPI)
│   ├── model/client.py    # DeepSeek API Client（保留 reasoning_content）
│   ├── agent/             # loop.py / state.py / prompt.py
│   ├── tools/             # registry / files / search / edit / command / git
│   └── security/sandbox.py# 路径沙箱 + 命令黑名单
├── tests/                 # pytest 测试（20 项）
├── benchmarks/            # Benchmark 任务与结果
├── prompts/               # 系统提示词副本
├── workspace/             # Agent 可操作目录（沙箱根）
├── logs/                  # 运行日志（含每轮 reasoning）
├── .env.example           # 环境变量模板
└── requirements.txt
```

## 安装

```bash
cd ~/v4-flash-agent
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
```

## 配置

```bash
cp .env.example .env
# 编辑 .env 填入真实 Key
```

`.env` 格式：

```
DEEPSEEK_API_KEY=你的Key
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
```

安全说明：API Key 仅存于 `.env`，已被 `.gitignore` 忽略，绝不会写入代码、Git、日志或输出给用户。

## 使用

### CLI

```bash
source .venv/bin/activate
python -m app.main "修复这个项目的登录 Bug"
```

### API Server

```bash
source .venv/bin/activate
uvicorn app.server:app --host 0.0.0.0 --port 8000
```

调用：

```bash
curl -X POST http://127.0.0.1:8000/v1/agent/run \
  -H "Content-Type: application/json" \
  -d '{"task": "在 workspace 中创建 hello.py"}'

curl http://127.0.0.1:8000/health   # 健康检查
```

## 测试

```bash
source .venv/bin/activate
python -m pytest tests/ -v
```

## Benchmark

```bash
source .venv/bin/activate
python benchmarks/benchmark.py
```

## 安全边界

- 文件操作强制限定在 `workspace/` 内，`../../` 逃逸会被拒绝（如 `../../etc/passwd`）
- 命令黑名单：`rm`、`sudo`、`shutdown`、`reboot`、`mkfs`、`diskutil erase`、`git reset --hard`、`git clean -fd`、`git push --force` 等一律拒绝
- 模型固定为 `deepseek-v4-flash`，模型不可用时停止并报告，绝不自行切换
