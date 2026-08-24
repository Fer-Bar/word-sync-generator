# Agent Instructions
- Activate venv with: source .venv/bin/activate
## Scope
-  Pon info relevante en README.md
## Tooling
- Use Python 3.12 with `uv`.
- `uv run` uses the project virtualenv at `.venv`.
- Install or sync packages only when necessary:
  - If dependencies are missing/out of sync, run `uv sync --dev`.
  - To add a runtime dependency, run `uv add <package>`.
  - To add a development dependency, run `uv add --dev <package>`.

## Architecture
- Keep business logic in services, not in signals.
- Keep API views thin: orchestrate request/response and delegate to services.
- Models enforce integrity and relationships.
- Keep one responsibility per function; prefer pure functions when feasible.
- Avoid global state; prefer dependency injection.
- Minimal comments: only when intent isn't obvious from clear naming and types. Use docstrings for public APIs
- Modules cohesive; names descriptive
- Clarity first prefer simple, readable solutions over cleverness
## Style
- Follow PEP 8 and lint with Ruff.
- Use f-strings.
- Prefer `pathlib` over `os.path`.
- Prefer `datetime` + `zoneinfo` for time handling.
- Use logging instead of print statements in app code.
- Ruff configuration lives in `pyproject.toml`.
- Ruff uses a 120-character line length and targets Python 3.12.
- Enabled rule families: `E`, `F`, `I`, `UP`, and `B`.
- Ruff respects `.gitignore` and force-excludes `.venv`, `venv`, `env`, `ENV`, `.uv-cache`, and `__pycache__`.

## Documentation and checks
- Public functions/classes should have short docstrings when intent is not obvious.
- Keep comments for invariants, non-obvious complexity, or rationale ("why", not "what")

