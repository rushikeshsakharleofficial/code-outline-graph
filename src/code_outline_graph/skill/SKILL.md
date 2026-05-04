# code-outline-graph Skill

**MANDATORY: Use this before any file read, grep, or search operation.**

## Hard Rule

```
NEVER use Read/Grep/Glob on source files without first checking the outline index.
```

If you're about to read a file → STOP → use `list_outline` or `resolve_edit_target` first.

---

## The Confirm-Before-Read Protocol

```
Step 1 — Resolve (no body, just metadata):
  resolve_edit_target({"description": "authentication middleware"})
  → [{name: "authenticate", file: "auth.py", start: 45, end: 89,
      signature: "def authenticate(token: str) -> User"}]

Step 2 — Confirm (AI picks correct candidate from signatures)

Step 3 — Read ONLY that body:
  read_symbol_body({"name": "authenticate", "file": "auth.py"})
  → 44 lines instead of 300-line file
```

Token savings: 10x–50x per edit.

---

## Tool Reference

| What you need | Tool to use |
|---------------|------------|
| Find function/class to edit | `resolve_edit_target({"description": "..."})` |
| Read one function body | `read_symbol_body({"name": "...", "file": "..."})` |
| All symbols in file | `list_outline({"file": "..."})` |
| Compressed signatures only | `get_outline_summary({"file": "..."})` |
| Imports + top of file | `get_file_header({"file": "..."})` |
| Find by name/keyword | `find_by_keyword({"query": "..."})` |
| Exact symbol metadata | `get_symbol({"name": "..."})` |
| Read specific lines | `get_line_range({"file": "...", "start": N, "end": M})` |
| Index a project | `index_project({"path": "..."})` |

---

## Patterns by Task

### Editing a function
```
resolve_edit_target({"description": "user login handler"})
→ pick from candidates
read_symbol_body({"name": "login", "file": "views/auth.py"})
→ edit with exact line range from start_line/end_line
```

### Understanding a file
```
get_outline_summary({"file": "src/components/Dashboard.js"})
→ see all components, hooks, functions at a glance
read_symbol_body only for what you need
```

### Finding where something is defined
```
find_by_keyword({"query": "createShift"})
→ get file + line range instantly
```

### Getting imports / top-of-file context
```
get_file_header({"file": "src/api/routes.py"})
→ shebang + imports + module constants only
```

### Reviewing a component without reading it all
```
list_outline({"file": "src/components/ShiftCard.js"})
→ all function/class symbols with line ranges
```

---

## After Every Code Change

**MANDATORY:** After editing or creating any source file, run:

```bash
code-outline-graph update .
```

This keeps the index current so future symbol lookups reflect your changes. If the MCP server is running, the file watcher handles this automatically — but always run it manually after bulk edits or when unsure.

---

## When to Fall Back to Read/Grep

Only if:
- `resolve_edit_target` returns empty results
- `find_by_keyword` returns empty results
- File is a config/JSON/YAML (no symbols to index)

---

## CLI Commands (terminal)

```bash
code-outline-graph build .          # index project + write .mcp.json + Codex + Gemini configs
code-outline-graph update .         # reindex changed files
code-outline-graph search <query>   # search from terminal
code-outline-graph outline <file>   # show file symbols
code-outline-graph status           # show index stats
code-outline-graph install-skill    # install this skill to ~/.claude/skills/
```
