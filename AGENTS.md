# Repository Guidelines

## Project Structure & Module Organization
`src/code_outline_graph/` contains the package. Keep modules focused: `db.py` owns SQLite storage, `parser.py` extracts symbols with tree-sitter, `indexer.py` handles indexing and freshness checks, `search.py` ranks results, `watcher.py` monitors file and git changes, `server.py` exposes MCP tools, and `cli.py` wires terminal commands. Tests live in `tests/`. Top-level files are limited to packaging and docs such as `pyproject.toml`, `README.md`, and generated local config like `.mcp.json`.

## Build, Test, and Development Commands
`python -m pip install -e .` installs the package in editable mode.
`python -m pip install pytest pytest-asyncio` installs the current test dependencies.
`python -m build` builds wheel and sdist artifacts for release checks.
`python -m pytest` runs the test suite; today this is mainly for tests added during a change.
`code-outline-graph build .` smoke-tests indexing against a local repository.
`code-outline-graph serve .` starts the MCP server over stdio for this project.

## Coding Style & Naming Conventions
Target Python 3.11+ with 4-space indentation. Follow the existing naming pattern: `snake_case` for functions and variables, `PascalCase` for classes, and uppercase constants such as `PROJECT_STATE_DIR`. Prefer explicit imports, short functional docstrings, and type hints on public functions. No formatter or linter is configured in-repo, so match neighboring code and avoid style-only churn.

## Testing Guidelines
Use `pytest` and `pytest-asyncio`, especially for async MCP server behavior. Name files `test_*.py` and test functions `test_*`. Prioritize parser extraction, database/index freshness, CLI commands, and MCP tool responses.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commits: `feat:`, `fix:`, `docs:`, and `chore:`. Keep subjects short and imperative, for example `feat: add Kotlin import parsing`. Pull requests should describe the behavior change, list validation commands, and include sample CLI output or MCP request/response snippets when tool behavior changes. Link the related issue when one exists.

## Configuration Tips
Do not commit local artifacts such as `.mcp.json`, `.code-outline-graph/`, `*.db`, `.env`, or virtual environments. Prefer repo-relative example paths in docs and tests instead of machine-specific absolute paths.
