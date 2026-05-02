# code-outline-graph

MCP server for symbol-level code indexing. Indexes codebases with tree-sitter, stores exact line ranges in SQLite, and lets AI agents read only the lines they need.

**Key feature:** Confirm-before-read flow. AI resolves edit target → gets signatures only → reads body only after confirming. 10x–50x fewer tokens per edit vs reading full files.

## Install

```bash
pip install -e .
```

## Add to MCP config

Claude Code (`~/.claude/claude.json`), Cursor, Codex, Gemini CLI — add:

```json
{
  "mcpServers": {
    "code-outline": {
      "command": "code-outline-graph"
    }
  }
}
```

## Workflow

```
1. index_project({"path": "/your/project"})
2. resolve_edit_target({"description": "authentication middleware"})
   → [{name: "authenticate", file: "auth.py", start: 45, end: 89, signature: "..."}]
3. read_symbol_body({"name": "authenticate", "file": "auth.py"})
   → 44 lines of source
4. Edit only those lines.
```

## Tools

| Tool | Description |
|------|-------------|
| `index_project` | Index directory, start file watcher |
| `list_outline` | All symbols in file with line ranges |
| `get_symbol` | Symbol metadata by name |
| `read_symbol_body` | Source lines for symbol only |
| `resolve_edit_target` | NL → top-5 candidates (signatures, no body) |
| `find_by_keyword` | Keyword search across symbol names |
| `get_line_range` | Read arbitrary line slice |
| `get_outline_summary` | Signatures only, ultra-compressed |

## Languages

Python, JavaScript, TypeScript, Go, Rust, Java, C, C++, Ruby, PHP, C#, Swift, Kotlin

## Design Principles

- **Zero telemetry** — no external calls, fully local
- **No file cap** — indexes any size project
- **Always fresh** — every read checks blake2b checksum, reindexes if stale
- **Watcher on by default** — git-HEAD-aware, 500ms debounce
