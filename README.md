# code-outline-graph

Symbol-level code indexer and MCP server. Parses your codebase with tree-sitter, stores symbols in SQLite + vector DB, and exposes a confirm-before-read protocol so AI assistants read only the symbols they need — not whole files.

**10x–50x fewer tokens** compared to reading files directly.

## Install

```bash
pip install code-outline-graph
```

## Quick Start

```bash
# Index your project (writes .mcp.json automatically)
cd your-project
code-outline-graph build .

# MCP server auto-configures via .mcp.json
# Supported clients: Claude Code, Cursor, Codex, any MCP-compatible client
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `code-outline-graph build [path]` | Index project + write `.mcp.json` |
| `code-outline-graph update [path]` | Reindex changed files only |
| `code-outline-graph search <query>` | Search symbols by keyword |
| `code-outline-graph outline <file>` | List all symbols in a file |
| `code-outline-graph status [path]` | Show index stats |
| `code-outline-graph serve [path]` | Start MCP server (stdio) |

## MCP Tools

The server exposes 9 tools to AI assistants:

| Tool | Description |
|------|-------------|
| `resolve_edit_target` | NL description → top-5 symbol candidates (signatures only, no body) |
| `read_symbol_body` | Read source lines for one symbol only |
| `list_outline` | All symbols in a file with line ranges |
| `get_outline_summary` | Compressed signatures-only outline |
| `get_file_header` | Imports + top-level constants only |
| `get_symbol` | Exact symbol metadata by name |
| `find_by_keyword` | Keyword search across all symbol names |
| `get_line_range` | Read arbitrary line slice from a file |
| `index_project` | Index a directory and start file watcher |

### Confirm-Before-Read Protocol

```
1. resolve_edit_target({"description": "user login handler"})
   → [{name: "login", file: "views/auth.py", start: 45, end: 89, signature: "def login(...)"}]

2. AI picks correct candidate from signatures (no body read yet)

3. read_symbol_body({"name": "login", "file": "views/auth.py"})
   → 44 lines instead of 300-line file
```

## Supported Languages

Python, JavaScript, TypeScript, TSX, Go, Rust, Java, C, C++, C#, Ruby, PHP, Swift, Kotlin, JSON, YAML, TOML, INI

## Architecture

```
cli.py          CLI entry point — build/update/search/outline/status/serve
server.py       MCP server — 9 tools, file watcher lifecycle
indexer.py      Orchestrates parse → checksum → DB upsert → embeddings
parser.py       tree-sitter parsing → Symbol extraction per language
db.py           SQLite + sqlite-vec — symbols table + FTS5 + vector index
search.py       FTS search, keyword search, vector search, resolve_edit_target
watcher.py      watchdog file watcher — debounced reindex + git HEAD tracking
embeddings.py   fastembed vector embeddings for semantic search
paths.py        Per-project DB path resolution (~/.cache/code-outline-graph/)
```

Each project gets its own SQLite DB at `~/.cache/code-outline-graph/<hash>/vectors.db`. The watcher reindexes files on save and reindexes the whole project on git branch switches.

## MCP Configuration

`build` auto-writes `.mcp.json` to your project root:

```json
{
  "mcpServers": {
    "code-outline": {
      "command": "code-outline-graph",
      "args": ["serve"]
    }
  }
}
```

## Development

```bash
pip install -e ".[dev]"
pytest                        # run all tests
pytest tests/test_parser.py   # run single test file
```

## License

MIT
