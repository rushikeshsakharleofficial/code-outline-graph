# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Commands

```bash
pip install -e ".[dev]"   # install with dev dependencies
pytest                    # run all tests
pytest tests/test_parser.py   # run single test file
code-outline-graph build .    # rebuild local index + MCP configs
code-outline-graph update .   # reindex changed files only
code-outline-graph status .   # inspect indexed project state
```

Build for distribution:
```bash
python -m build   # produces sdist + wheel in dist/
```

## Architecture

Single Python package at `src/code_outline_graph/`. Each module has a clear owner:

| Module | Role |
|--------|------|
| `cli.py` | Entry point. CLI commands (`build`, `update`, `search`, `outline`, `status`, `serve`, `prune`, `doctor`, `install-skill`). Also writes MCP configs and sentinel-bounded instruction blocks into `AGENTS.md`/`GEMINI.md`. |
| `server.py` | MCP server (stdio). 11 tools. Lazily initializes `Database`, `Indexer`, `Searcher` singletons per project path. Watcher lifecycle tied to `index_project` with `watch=true`. |
| `indexer.py` | Orchestrates full project indexing. Phase 1: serial walk + skip callbacks. Phase 2: parallel parse via `ThreadPoolExecutor`. Phase 3: bulk DB write. Phase 4: optional background large-file indexing. `ensure_fresh()` called before every MCP read. |
| `parser.py` | tree-sitter parsing → `Symbol` extraction per language. Language detection by extension. One `SymbolParser` per thread (thread-local). |
| `db.py` | SQLite + sqlite-vec. Schema: `symbols` (main table), `symbols_fts` (FTS5 BM25, porter tokenizer), `vec_symbols` (384-dim embeddings), `indexed_files` (checksum + mtime_ns fast-path). `bulk_insert_all` drops FTS triggers during batch, rebuilds once. WAL mode, 64 MB page cache. |
| `search.py` | `fts_search` (FTS5), `keyword_search` (LIKE), `vec_search` (sqlite-vec KNN), `resolve_edit_target` (hybrid RRF merge of FTS + vec). |
| `watcher.py` | watchdog-based file watcher. Debounced per-file reindex on save; removes symbols for deleted files. Opt-in only (`serve --watch` or `CODE_OUTLINE_WATCH=1`). |
| `embeddings.py` | fastembed wrapper. Lazy singleton. Background batch embedding thread in `Indexer`. |
| `paths.py` | Per-project DB path: `.code-outline-graph/index.db` inside project root. |

## Key Design Decisions

**Freshness check order:** `is_file_current` uses `(file_size, mtime_ns)` fast path first; falls back to blake2b checksum only on mtime mismatch. This avoids hashing unchanged files.

**File freshness on MCP reads:** Every `list_outline`, `get_symbol`, `read_symbol_body`, `get_line_range`, `get_file_header` call `indexer.ensure_fresh(file_path)` before touching the DB.

**Large files (≥512 KB):** Skipped by default. Enable background indexing with `CODE_OUTLINE_BACKGROUND_LARGE_FILES=1` or `--background-large-files`.

**Embeddings:** Disabled by default. Enable with `--embeddings` or `CODE_OUTLINE_ENABLE_EMBEDDINGS=1`. Vector dim is 384 (fastembed MiniLM-L6).

**Workers:** Default `min(4, cpu_count)`. Override with `CODE_OUTLINE_INDEX_WORKERS=N` or `--workers N`.

**Low-end hardware:** Set these env vars to reduce RAM and CPU pressure:
```
CODE_OUTLINE_INDEX_WORKERS=1      # single parse thread
CODE_OUTLINE_SQLITE_CACHE_MB=8    # page cache (default 64 MB)
CODE_OUTLINE_SQLITE_MMAP_MB=0     # disable mmap (default 256 MB)
CODE_OUTLINE_NICE=15              # nice worker threads to reduce CPU priority
```
Add to shell profile or project `.env` (not indexed). Disable the `PostToolUse` hook in `.claude/settings.json` to stop auto-reindex after every edit.

**Secret files:** `.env`, `.env.local`, `.env.production`, `.env.development` are always skipped in `iter_indexable_files`.

**Skipped dirs:** `node_modules`, `__pycache__`, `.git`, `dist`, `build`, `.venv`, `venv` — plus any dotfile dirs and `.gitignore` matches.

## Naming Conventions

- CLI handler functions named `cmd_*` in `cli.py`
- `snake_case` for functions/variables, `PascalCase` for classes
- Tests named `test_*`, function-style (no test classes needed)

## Commit Style

Conventional Commits: `fix:`, `ci:`, `chore:`, `feat:`. Short imperative subjects, e.g. `fix: normalize project paths in CLI`.

## After Code Changes

Run `code-outline-graph update .` to keep the local index current. The `SessionStart` hook in `.claude/settings.json` does this automatically at session start.
