# Repository Guidelines

## Project Structure & Module Organization
Core package lives in `src/code_outline_graph/`. Main modules: `parser.py` for tree-sitter extraction, `indexer.py` for project indexing, `db.py` for SQLite storage, `search.py` for FTS/vector lookup, `watcher.py` for file change tracking, `server.py` for MCP tools, and `cli.py` for the `code-outline-graph` entrypoint. Tests live in `tests/`, with reusable fixtures under `tests/fixtures/`. Repo docs start in `README.md`; release automation lives in `.github/workflows/`.

## Build, Test, and Development Commands
Use Python 3.11+.

```bash
python -m venv venv
. venv/bin/activate
pip install -e .
pip install pytest pytest-asyncio
pytest
```

Useful local commands:

```bash
pytest tests/test_indexer.py      # run one test module
python -m build                   # build sdist/wheel
code-outline-graph build .        # generate local index + .mcp.json
code-outline-graph status .       # inspect indexed project state
```

## Coding Style & Naming Conventions
Follow existing Python style: 4-space indentation, type hints where helpful, small focused functions, and module-level responsibilities kept clear. Use `snake_case` for functions, variables, and test names; `PascalCase` for classes; keep CLI handlers named `cmd_*` to match `cli.py`. Prefer explicit paths and deterministic return values because this project writes config and index files.

## Testing Guidelines
Tests use `pytest` with simple function-style cases named `test_*`. Add targeted unit tests beside the affected area, and use fixtures from `tests/conftest.py` or `tests/fixtures/` when behavior depends on workspace layout. Cover parser, indexer, search, and CLI behavior whenever logic changes. Run `pytest` before opening a PR; for bug fixes, add a regression test first.

## Commit & Pull Request Guidelines
Recent history uses Conventional Commit prefixes like `fix:`, `ci:`, and `chore:`. Keep subjects short and imperative, for example `fix: normalize project paths in CLI`. PRs should explain behavior changes, list test commands run, and note any user-visible CLI or MCP output changes. Include sample output when changing indexing, config generation, or search results.

## Security & Configuration Tips
Do not commit generated project indexes, local virtualenv contents, or secrets. Changes touching indexing rules should preserve the current expectation that ignored or sensitive files are not exposed through the outline or MCP server.

<!-- code-outline-graph:start -->
## code-outline-graph MCP Tools

This project is indexed with [code-outline-graph](https://github.com/rushikeshsakharleofficial/code-outline-graph). MCP server name: `code-outline`. Use these tools instead of reading source files directly (10x–50x fewer tokens).

| Tool | When to use |
|------|-------------|
| `resolve_edit_target(description)` | Find function/class by natural language — returns signatures only, no body |
| `read_symbol_body(name, file)` | Read one symbol's source lines (never the full file) |
| `list_outline(file)` | All symbols + line ranges in a file |
| `get_outline_summary(file)` | Compressed signatures view |
| `find_by_keyword(query)` | Search all indexed symbol names |
| `get_file_header(file)` | Imports + top-level constants only |
| `get_symbol(name)` | Exact symbol metadata |
| `get_line_range(file, start, end)` | Read arbitrary line slice |

Fall back to direct file reads only if these return empty results.

**After every code change:** run `code-outline-graph update .` to keep the index current.
<!-- code-outline-graph:end -->
