---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 6c346b738202fe25c8b31fee4a61768d_1ebc1a85a26d11f1bc17525400826444
    ReservedCode1: mGEldpmBFVO7NO3+P+QQkaAGFttw3QNnkS4ORaPPmx8bw7/Ww4Q8JG+rciFSM3g1UqM5+IxWF2yeXiGWWTGkUDBr+g/VgOhdcMV7LnNHhgP1jfdainJS5pDhYIcJwcuC8Y0tqHNiBuhXxtzUNeCarXBVDiobrvX9lEduYlwFs3/qyRuOd9L0TrWf/Ic=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 6c346b738202fe25c8b31fee4a61768d_1ebc1a85a26d11f1bc17525400826444
    ReservedCode2: mGEldpmBFVO7NO3+P+QQkaAGFttw3QNnkS4ORaPPmx8bw7/Ww4Q8JG+rciFSM3g1UqM5+IxWF2yeXiGWWTGkUDBr+g/VgOhdcMV7LnNHhgP1jfdainJS5pDhYIcJwcuC8Y0tqHNiBuhXxtzUNeCarXBVDiobrvX9lEduYlwFs3/qyRuOd9L0TrWf/Ic=
---

# V4-Flash Coding Agent — Security Policy

## Reporting a Vulnerability

If you discover a security issue in this project (path traversal, sandbox escape, secret leakage, upload validation bypass, network exposure, etc.):

- **Do NOT** open a public issue that describes the exploit.
- Send a private report to the maintainer with:
  - Affected file / endpoint / component.
  - A minimal reproduction (no real credentials, no private project data).
  - Impact description.

We will acknowledge the report, investigate, and work toward a fix before public disclosure.

## Security Model (short version)

1. **Loopback only by default.** The server binds to `127.0.0.1` unless `HOST` is explicitly changed. This is a coding agent that can read/modify files and run commands — never expose it to your LAN by default.
2. **Sandbox boundary.** All file / command / git / search / edit operations are validated against the active project root. Path traversal (`../`), absolute paths outside the sandbox, and sensitive segments are rejected.
3. **Server-computed upload paths.** Upload targets are computed and validated by the backend; the frontend never decides final filesystem paths. Sensitive entries (`.env*`, `.git/`, `node_modules`, `__pycache__`) are skipped.
4. **API key handling.** Keys are read only from `.env` (git-ignored). They never appear in source, frontend code, logs, or git history. `.env.example` contains placeholders only.
5. **Agent scope.** The agent can only access files under the active project — files you did not explicitly select are not touched.

## Scope

- In scope: the local web server, file/git APIs, upload pipeline, sandbox enforcement, agent tool boundary.
- Out of scope: third-party API provider security (e.g. DeepSeek).

## Reporting SLA

- Acknowledgment: within 5 business days.
- Initial assessment / fix plan: as soon as practical depending on severity.
*（内容由AI生成，仅供参考）*
