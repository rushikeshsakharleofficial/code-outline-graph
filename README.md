# code-outline-graph

Symbol-level code indexer and MCP server. Parses your codebase with tree-sitter, stores symbols in SQLite + vector DB, and exposes a confirm-before-read protocol so AI assistants read only the symbols they need — not whole files.

**10x–50x fewer tokens** compared to reading files directly.

## Install

```bash
pip install code-outline-graph
```

## Quick Start

```bash
cd your-project
code-outline-graph build .
```

`build` runs once and configures everything — index, MCP configs, hooks, skill. Output:

```
╔══════════════════════════════════════════════════════════╗
║         code-outline-graph  •  Building Index            ║
╚══════════════════════════════════════════════════════════╝

[1/7] Indexing /home/user/myproject ...

      SKIP   .env                        (secret file)
      WARN   src/broken.py               parse error line 42
      OK     src/auth/views.py           23 symbols   0.04s
      OK     src/api/routes.py           45 symbols   0.11s

      src/auth/      →   3 files    67 symbols
      src/api/       →   8 files   203 symbols

      [████████████████████] 100%  186 files · 1789 symbols  →  Done!
      Skipped: 1  •  Errors: 1  •  Time: 3.2s

[2/7] Writing Claude Code / Cursor MCP config (.mcp.json) ...
      Written: /home/user/myproject/.mcp.json  ✓
[3/7] Writing Codex CLI config + hooks ...
      Written: .codex/config.toml  ✓
      Written: .codex/hooks.json   ✓
[4/7] Writing Gemini CLI config + hooks ...
      Written: .gemini/settings.json  ✓
[5/7] Writing Claude Code SessionStart + PostToolUse hooks ...
      Written: .claude/settings.json  ✓
[6/7] Writing AI instruction blocks ...
      Updated: AGENTS.md  ✓
      Updated: GEMINI.md  ✓
[7/7] Installing Claude Code skill ...
      Installed: SKILL.md     ✓
      Installed: examples.md  ✓

══════════════════════════════════════════════════════════
  Build complete in 5.1s
  186 files  •  1789 symbols  •  1 skipped  •  1 error
══════════════════════════════════════════════════════════
```

## CLI Commands

| Command | Description |
|---------|-------------|
| `code-outline-graph build [path]` | Index project + write MCP configs for all clients |
| `code-outline-graph update [path]` | Reindex changed files only |
| `code-outline-graph search <query>` | Search symbols by keyword |
| `code-outline-graph outline <file>` | List all symbols in a file |
| `code-outline-graph status [path]` | Show index stats |
| `code-outline-graph serve [path]` | Start MCP server (stdio) |
| `code-outline-graph install-skill` | Install Claude Code skill to `~/.claude/skills/` |

## MCP Tools

The server exposes 10 tools to AI assistants:

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
| `update_project` | Reindex only changed files (faster than `index_project`) |

### Confirm-Before-Read Protocol

```
1. resolve_edit_target({"description": "user login handler"})
   → [{name: "login", file: "views/auth.py", start: 45, end: 89, signature: "def login(...)"}]

2. AI picks correct candidate from signatures (no body read yet)

3. read_symbol_body({"name": "login", "file": "views/auth.py"})
   → 44 lines instead of 300-line file
```

## Supported Languages

50+ languages and formats — symbols extracted where applicable, files tracked for all others.

**Systems & Backend**
Python, JavaScript/JSX, TypeScript/TSX, Go, Rust, Java, C, C++, C#, Kotlin, Swift, Dart, Scala, Groovy, Zig, Lua

**Web & Frontend**
HTML, CSS, SCSS, Sass, Less, Vue, Svelte

**Shell & Scripting**
Bash/Zsh (`.sh`/`.bash`/`.zsh`), Fish, PowerShell, Batch/CMD, Perl, R

**Functional**
Elixir, Erlang, Haskell, OCaml, Clojure/ClojureScript, Nix

**Data & Config**
JSON, YAML, TOML, INI/CFG, XML, PLIST, SQL, SQLite (`.db` — tables/views), CSV

**Infrastructure & Build**
Terraform/HCL, Protobuf, GraphQL, Makefile, Dockerfile

**Mac / Windows system files** (`.DS_Store`, `.exe`, `.dll`, `.lnk`, etc.) are binary and are skipped automatically.

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

`build` auto-configures all supported clients in one shot:

| Client | MCP config | SessionStart hook |
|--------|-----------|-------------------|
| Claude Code / Cursor | `.mcp.json` | `.claude/settings.json` |
| Codex CLI | `.codex/config.toml` | `.codex/hooks.json` |
| Gemini CLI | `.gemini/settings.json` | `.gemini/settings.json` |

It also appends usage instructions (sentinel-bounded, safe to re-run) to `AGENTS.md` and `GEMINI.md` so clients that read those files know to use the MCP tools.

The `SessionStart` hook runs `code-outline-graph update .` at the start of every AI session, keeping the index fresh without manual intervention.

## Claude Code Skill

`build` automatically installs the Claude Code skill to `~/.claude/skills/code-outline-graph/` (`SKILL.md` + `examples.md`). The skill teaches Claude the confirm-before-read protocol and tool reference.

To install manually or update after upgrading:

```bash
code-outline-graph install-skill
```

## Development

```bash
pip install -e ".[dev]"
pytest                        # run all tests
pytest tests/test_parser.py   # run single test file
```

## License

MIT
