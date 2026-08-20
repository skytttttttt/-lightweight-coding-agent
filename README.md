---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 6c346b738202fe25c8b31fee4a61768d_0214e6209bca11f19bec525400826444
    ReservedCode1: H/2dvPsMrkUkGhHB9z9epXw7j1QlcYyN9ClliRV52wKJ6gfEa4Sg9g4qonmj3oy+bklSDZaksVCapJOEaf8zBErQmI91tyLjIgr2BxaMwCmbmzM76vaKVThGVnkRz3LDZMGw3jG/lXD1iOvivYkIDOiFHMmpjRpieqt7HmzO0BJkhlNFcJ4eylWlpU0=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 6c346b738202fe25c8b31fee4a61768d_0214e6209bca11f19bec525400826444
    ReservedCode2: H/2dvPsMrkUkGhHB9z9epXw7j1QlcYyN9ClliRV52wKJ6gfEa4Sg9g4qonmj3oy+bklSDZaksVCapJOEaf8zBErQmI91tyLjIgr2BxaMwCmbmzM76vaKVThGVnkRz3LDZMGw3jG/lXD1iOvivYkIDOiFHMmpjRpieqt7HmzO0BJkhlNFcJ4eylWlpU0=
---



# V4-Flash Coding Agent

运行于 macOS + Python 的自主 Coding Agent，核心模型 **DeepSeek V4-Flash**。
用户输入编程任务后，Agent 自动完成：检查项目 → 搜索代码 → 读取文件 → 制定修改方案 → 修改代码 → 运行测试 → 分析失败 → 自动修复（最多 2 次）→ 重新验证 → 检查 Git Diff → 输出最终结果。

## 功能特性

- **7 个工具**：`list_files` / `read_file` / `search_code` / `write_file` / `edit_file` / `run_command` / `git_diff`
- **Sandbox 安全沙箱**：所有文件操作限制在 `workspace/` 内，拒绝 `../../` 路径逃逸
- **Agent Loop**：最大 30 turns，完整保留每轮 `reasoning_content`（Thinking）与 `tool_calls`
- **Repair 协议**：同一问题最多自动修复 2 次，连续失败自动停止
- **GOALS 协议**：修改 2 个及以上文件时先输出计划
- **CLI 与 API 双入口**
- **可视化 Web 页面**：浏览器中输入任务即可运行 Agent，实时展示执行轨迹与最终结果

## 项目结构

```
v4-flash-agent/
├── app/
│   ├── main.py            # CLI 入口 (python -m app.main "任务")
│   ├── config.py          # 配置加载 (.env)
│   ├── server.py          # API Server (FastAPI)
│   ├── model/client.py    # DeepSeek API Client（保留 reasoning_content，带瞬时故障重试）
│   ├── agent/             # loop.py / state.py / prompt.py
│   ├── tools/             # registry / files / search / edit / command / git
│   └── security/sandbox.py# 路径沙箱 + 命令黑名单
├── tests/                 # pytest 测试（21 项）
├── benchmarks/            # Benchmark 任务与结果
├── prompts/               # 系统提示词副本
├── web/index.html         # 可视化 Web 页面（挂载于 API Server）
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

### Web 页面

启动 API Server 后（同上命令），浏览器直接访问：

```bash
# 启动（挂载 Web 页面）
source .venv/bin/activate
uvicorn app.server:app --host 0.0.0.0 --port 8000

# 访问
open http://127.0.0.1:8000
```

页面功能：

- **健康检查**：顶部徽章实时显示 API 服务与模型状态（`GET /health`）
- **任务输入**：在文本框中输入编程任务，点击「运行 Agent」（或 `Cmd/Ctrl + Enter`）调用 `POST /v1/agent/run`
- **执行过程**：按 Turn 折叠展示每轮推理（Thinking）、回复与工具调用明细（名称 / 参数 / 执行结果）
- **最终结果**：展示完成状态、执行轮次、停止原因、自动修复次数、最终答案与运行日志路径

页面为独立静态文件（`web/index.html`），已随 API Server 自动挂载，无需额外配置。

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
*（内容由AI生成，仅供参考）*
*（内容由AI生成，仅供参考）*
