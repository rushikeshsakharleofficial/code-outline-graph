# code-outline-graph

Symbol-level code indexer MCP server. Instead of reading full files, AI agents get exact line ranges for every function, class, and import — then read only what they need.

**10x–50x fewer tokens per edit** vs reading full files.

[![PyPI](https://img.shields.io/pypi/v/code-outline-graph)](https://pypi.org/project/code-outline-graph/)
[![Python](https://img.shields.io/pypi/pyversions/code-outline-graph)](https://pypi.org/project/code-outline-graph/)

---

## How it works

```
Normal AI workflow:          code-outline-graph workflow:
─────────────────            ────────────────────────────
Read 300-line file           resolve_edit_target("auth middleware")
→ 300 tokens                 → [{name: "authenticate", start: 45, end: 89}]
                             read_symbol_body("authenticate", "auth.py")
                             → 44 lines = 44 tokens
```

The index maps every symbol (function, class, method, import) to its exact file + line range. Every file save updates the map automatically.

---

## Install

```bash
pip install code-outline-graph
```

Requirements: Python 3.11+

---

## Quick Start

### 1. Index your project

```bash
cd /your/project
code-outline-graph build .
```

Output:
```
Indexing /your/project...
Done: 186 files, 1789 symbols, 5 skipped
DB: /your/project/.code-outline-graph/index.db
MCP config written to /your/project/.mcp.json
```

This stores the index in `/your/project/.code-outline-graph/index.db` and creates `.mcp.json` in your project automatically.

### 2. Add to Claude Code (global)

Edit `~/.claude/claude.json`:
```json
{
  "mcpServers": {
    "code-outline": {
      "command": "code-outline-graph",
      "args": ["serve", "/your/project"]
    }
  }
}
```

Restart Claude Code. Done.

### 3. Add to Cursor

Settings → MCP → Add server:
```json
{
  "code-outline": {
    "command": "code-outline-graph",
    "args": ["serve", "/your/project"]
  }
}
```

### 4. Add to Codex / Gemini CLI / any MCP client

Same JSON config. Works with any tool that supports MCP (stdio transport).

---

## MCP Tools (for AI agents)

| Tool | What it does |
|------|-------------|
| `index_project(path)` | Index directory, start file watcher |
| `resolve_edit_target(description)` | NL → top-5 symbol candidates (signatures only, no body) |
| `read_symbol_body(name, file)` | Read source for one symbol only |
| `list_outline(file)` | All symbols in file with line ranges |
| `get_outline_summary(file)` | Signatures only, ultra-compressed |
| `get_file_header(file)` | Imports + shebang + top-level constants |
| `get_symbol(name)` | Exact symbol metadata lookup |
| `find_by_keyword(query)` | Keyword search across all symbols |
| `get_line_range(file, start, end)` | Read arbitrary line slice |

---

## CLI Commands

```bash
# Index a project (run once — watcher keeps it fresh after)
code-outline-graph build [path]

# Reindex only changed files
code-outline-graph update [path]

# Search symbols from terminal
code-outline-graph search --project [path] <query>

# List all symbols in a file
code-outline-graph outline --project [path] <file>

# Show index stats
code-outline-graph status [path]

# Start MCP server manually (stdio)
code-outline-graph serve [path]
```

---

## The Confirm-Before-Read Flow

No other tool enforces this. AI resolves intent → sees signatures → confirms target → reads only that body:

```
AI: resolve_edit_target({"description": "user login validation"})
→ [
    {name: "validate_login", file: "auth/views.py", start: 45, end: 89,
     signature: "def validate_login(username, password) -> bool"},
    {name: "LoginView", file: "auth/views.py", start: 12, end: 44,
     signature: "class LoginView(APIView)"}
  ]

AI picks "validate_login"

AI: read_symbol_body({"name": "validate_login", "file": "auth/views.py"})
→ 44 lines returned (not the full 300-line file)
```

---

## Languages Supported

Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, C#, Ruby, PHP, Swift, Kotlin

---

## Key Design

| Feature | Detail |
|---------|--------|
| Zero telemetry | No external calls, fully local |
| No file cap | Indexes any size project |
| Project-local index | Stores SQLite data in `[project]/.code-outline-graph/index.db` |
| Always fresh | Every read checks blake2b checksum, reindexes if stale |
| Watcher on by default | 500ms debounce, git-HEAD-aware (detects `git pull`) |
| No daemon | Single process, no background service |
| Hybrid search | FTS5 (fast exact) + sqlite-vec embeddings (semantic) + RRF merge |

---

## How resolve_edit_target works

1. **FTS5** — porter stemming (`authentication` → matches `authenticate`)
2. **sqlite-vec** — local ONNX embeddings (BAAI/bge-small-en-v1.5, 384-dim) for semantic fallback when word doesn't appear in symbol name
3. **RRF merge** — Reciprocal Rank Fusion combines both ranked lists

Returns signatures only. Body never fetched until AI explicitly calls `read_symbol_body`.

---

## vs Other Tools

| | code-outline-graph | jCodeMunch | CodeSight | cocoindex |
|--|--|--|--|--|
| Confirm-before-read | ✅ | ❌ | ❌ | ❌ |
| Zero telemetry | ✅ | ❌ calls home | ❌ optional | ✅ |
| No file cap | ✅ | ❌ 500 files | ❌ | ✅ |
| Watcher on by default | ✅ | ❌ opt-in | ❌ | ✅ (daemon) |
| Git-pull-aware reindex | ✅ | ❌ | ❌ | ❌ |
| No daemon required | ✅ | ✅ | ✅ | ❌ Rust daemon |

---

## Project Structure

```
src/code_outline_graph/
├── db.py          # SQLite schema + CRUD (symbols, FTS5, vec_symbols)
├── parser.py      # tree-sitter symbol extraction (13 languages)
├── indexer.py     # file/project indexer + freshness guarantee
├── search.py      # FTS5 + sqlite-vec + RRF hybrid search
├── embeddings.py  # fastembed ONNX wrapper (no PyTorch needed)
├── watcher.py     # watchdog + git HEAD watcher
├── server.py      # MCP server (9 tools)
└── cli.py         # CLI commands
```

---

## License

MIT
