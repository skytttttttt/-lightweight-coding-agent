---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 6c346b738202fe25c8b31fee4a61768d_1e090710a26d11f193c6525400f8a581
    ReservedCode1: Yi6oRhGEeLFqpxG/lTa7iuSMP39fseQ8vTPgdBh6sOfw5lI2DWRVSK0jxJ+ngYD9FROdX18nevincOcxQXk3v8Sgwsnsf/QbnEQDyuumTwx5XZxaljCtuRWQOxngXSbdBXpPNX+rUBfX6Jsn/Bc1Mrs0bKwrWBBGiEvWKnDBoY7XUzPBtLrqZW8EUmY=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 6c346b738202fe25c8b31fee4a61768d_1e090710a26d11f193c6525400f8a581
    ReservedCode2: Yi6oRhGEeLFqpxG/lTa7iuSMP39fseQ8vTPgdBh6sOfw5lI2DWRVSK0jxJ+ngYD9FROdX18nevincOcxQXk3v8Sgwsnsf/QbnEQDyuumTwx5XZxaljCtuRWQOxngXSbdBXpPNX+rUBfX6Jsn/Bc1Mrs0bKwrWBBGiEvWKnDBoY7XUzPBtLrqZW8EUmY=
---

# V4-Flash Coding Agent

A local-first AI coding agent that runs entirely on your own machine. You open (or upload) a project folder, give the agent a task, and it reads, edits, and tests the code inside **that project only** — powered by the DeepSeek-compatible chat completion API.

> No cloud sync. No telemetry. No background data collection. Your project files never leave your computer unless you choose to call an external API yourself.

---

## What is it?

V4-Flash Coding Agent is a desktop-style web workspace with:

- A **file explorer** that always mirrors the real active project on disk.
- A **Git panel** with live status, diffs and change tracking.
- An **Agent runner** that streams its reasoning/tool calls live (SSE) into a timeline.
- A **plan / tools / tests / verification** panel driven entirely by real backend data.
- A **local Python server** that hosts the web UI, the Agent loop, and all file/git/command operations inside a sandbox.

## What can it do?

- Load a local folder (via browser File System Access API, or by uploading).
- Run an agent that plans, searches, reads, edits files, runs commands, runs tests, and checks git status — all scoped to the active project.
- Visualize the full agent run: plan steps, tool calls, file changes, test results, timeline events.
- Support non-Git projects gracefully (Git shows `Not a Git repository`, everything else keeps working).
- Manage multiple imported projects, each stored under `workspace/projects/<project-id>/`, and switch between them.

## Architecture

```
Local Browser
      │
      │ HTTP / SSE
      ▼
Local Python Server
      │
      ├── Agent            (prompt / loop / state)
      ├── Tools            (command / file / git / search / edit)
      ├── Sandbox          (path boundary for every operation)
      ├── Project Manager  (active project, upload validation)
      ├── File API         (/api/files, /api/files/upload, /api/files/delete)
      ├── Git API          (/api/git/status, /api/git/diff, ...)
      └── Model API        (DeepSeek-compatible chat completions)
              │
              ▼
        Your API Provider
```

All agent execution happens on **your own computer**. The server binds to `127.0.0.1` by default so nothing is exposed to your local network.

## Requirements

- **Python 3.11+** (tested on 3.14)
- **Git** (optional — the UI degrades gracefully if missing or if the project is not a Git repository)
- A modern browser with ES2020+ support (Chrome/Edge for best support of File System Access API)
- A **DeepSeek-compatible API key** (or any OpenAI-compatible endpoint)

## Installation

```bash
git clone <your-fork-or-repo-url> v4-flash-agent
cd v4-flash-agent

# (recommended) create a virtual environment
python3 -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate

pip install -r requirements.txt
```

## Configuration

Copy the example env file and fill in your API key:

```bash
cp .env.example .env
# edit .env, set at least DEEPSEEK_API_KEY
```

```dotenv
# .env
DEEPSEEK_API_KEY=sk-...            # required to run the Agent
DEEPSEEK_BASE_URL=https://api.deepseek.com
DEEPSEEK_MODEL=deepseek-v4-flash
HOST=127.0.0.1                    # default: loopback only
PORT=8000                         # set 0 for an auto-selected free port
```

`.env` is git-ignored. **Never commit a real API key.**

## Run

```bash
python run.py
```

On start you will see an environment check (Python / Git / Model API), and then:

```
V4-Flash Coding Agent
Server running at:
  http://127.0.0.1:8000
```

Open the printed URL in your browser. If the default port is busy, `run.py` fails with a clear error — set `PORT=0` to auto-pick a free port (the actual URL is printed for you).

## Open Project

- **Open Folder (Mode A — recommended):** on browsers with File System Access API (Chrome/Edge), click **Open Folder**, pick any local directory, and the agent works directly against that directory.
- **Upload Folder / Upload Files (Mode B — import):** works in every browser. Files are safely imported into `workspace/projects/<project-id>/` by the backend after path validation. The display name and the physical folder are separated — you can name your project `My Cool Project` and it is stored under a sanitized id.

If a browser does not support direct folder access, the UI tells you to use **Upload Folder** instead.

## Run Agent

1. Make sure a project is loaded (File Explorer shows its files).
2. Type a task in the input box, e.g. `Add a function that returns the sum of two integers and add a test for it`.
3. Press **Run**. Watch the timeline stream the agent's plan, tool calls, file edits, command output, test results and verification — all real backend events.
4. Press **Stop** at any time to cancel the running session.

## Security Model

- **Loopback only:** server binds to `127.0.0.1` unless you explicitly set `HOST=0.0.0.0`.
- **Sandbox boundary:** every file / command / git / search / edit operation is validated against the active project root. Path traversal (`../`), absolute paths outside the sandbox, and sensitive segments are rejected.
- **Upload boundary:** upload targets are computed server-side; the frontend never decides the final path. `.env*`, `.git/`, `node_modules`, `__pycache__` and other sensitive entries are skipped.
- **API key:** read only from `.env`, never from source code, and never committed.
- **Agent scope:** the agent can only access files under the active project — nothing on your machine that you did not select.

## Supported OS / Browser

- **OS:** macOS (primary test platform), Linux, Windows (path handling is portable via `pathlib`; not yet CI-tested on Windows/Linux).
- **Browser:** any modern browser for full UI. Chrome / Edge additionally support **Open Folder** via File System Access API. Firefox / Safari can use **Upload Folder / Upload Files**.

## Troubleshooting

| Symptom | Likely cause / fix |
|---|---|
| `Model API Key Required` | `DEEPSEEK_API_KEY` is missing in `.env` — configure it, then restart. |
| Page shows `Backend unavailable` | Server not running / wrong port. Start `python run.py` and open the printed URL. |
| `Open Folder` button missing or no-op | Browser lacks File System Access API — use **Upload Folder**. |
| Git shows `Not a Git repository` | The active project has no `.git` — that is fine; file explorer and agent still work. |
| Port already in use | Set `PORT=0` (auto) or another free port; `run.py` prints the real URL. |
| No project after refresh | Active project is a server-side runtime state; re-open or re-upload your project. |

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md). Please read [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) and report security issues via [SECURITY.md](SECURITY.md).

## License

Released under the [MIT License](LICENSE).
*（内容由AI生成，仅供参考）*
