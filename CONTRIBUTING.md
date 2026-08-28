---
AIGC:
    Label: "1"
    ContentProducer: 001191440300708461136T1XGW3
    ProduceID: 6c346b738202fe25c8b31fee4a61768d_1f6faa5ea26d11f193c6525400f8a581
    ReservedCode1: Kz6BsQmjD4Re8+UgQVGyVl5ld2uMG16v0G/ELIhp9qPrzq6ZBGREChA7lHAna045lHbyVa+NP75mCYf6oKkf6pVhqYThG8vednTJdwF722xo8GKQf0oz8Wha6MUg9ehnWfXNU0Tm1LBfA+AaUild3z0+M7xrMHCjOZuM3s8baFmdttiRJKCBysnwwjk=
    ContentPropagator: 001191440300708461136T1XGW3
    PropagateID: 6c346b738202fe25c8b31fee4a61768d_1f6faa5ea26d11f193c6525400f8a581
    ReservedCode2: Kz6BsQmjD4Re8+UgQVGyVl5ld2uMG16v0G/ELIhp9qPrzq6ZBGREChA7lHAna045lHbyVa+NP75mCYf6oKkf6pVhqYThG8vednTJdwF722xo8GKQf0oz8Wha6MUg9ehnWfXNU0Tm1LBfA+AaUild3z0+M7xrMHCjOZuM3s8baFmdttiRJKCBysnwwjk=
---

# Contributing to V4-Flash Coding Agent

Thanks for your interest in contributing. This project is intentionally small and safety-focused — please read this before opening PRs.

## Ground rules

- **The Agent capability layer is frozen by design** (`app/agent/`, `app/model/`, `app/tools/`, `app/security/`, `benchmarks/` logic, `prompts/`). Changes there require a strong justification and a maintainer discussion first.
- Most contribution surface is: `app/server.py`, `app/config.py`, `run.py`, `web/` (UI), `tests/`, and documentation.
- No real API keys, tokens, personal paths, or private project files in any commit.
- New features must come with tests (`pytest tests/`) and must not break the existing suite.

## Development setup

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
pytest tests/          # keep the suite green
```

Run the server locally:

```bash
python run.py          # binds 127.0.0.1; set PORT=0 to auto-pick a port
```

## Workflow

1. Open an issue describing the problem / feature.
2. Fork the repo and create a feature branch.
3. Make focused changes with tests.
4. Run `pytest tests/` and verify the web UI manually if your change touches it.
5. Open a pull request referencing the issue.

## Commit conventions

- Use clear, imperative commit messages (`Fix upload conflict detection`, `Add project lifecycle states`).
- Keep generated artifacts out of the repo (`benchmarks/results/` is git-ignored).

## Code of conduct

All interactions are governed by [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md). Report violations privately to the maintainer.
*（内容由AI生成，仅供参考）*
