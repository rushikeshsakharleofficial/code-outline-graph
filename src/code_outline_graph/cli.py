from __future__ import annotations

import argparse
import json
import os
import shutil
import sys
import time

from .paths import ensure_project_db_path, resolve_project_path

_SENTINEL_START = "<!-- code-outline-graph:start -->"
_SENTINEL_END = "<!-- code-outline-graph:end -->"

_AI_INSTRUCTION_BLOCK = """{start}
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
| `update_project(path?)` | Reindex changed files |
| `prune_project(path?)` | Remove stale rows for deleted or ignored files |

Fall back to direct file reads only if these return empty results.

**After every code change:** run `code-outline-graph update .` to keep the index current.
{end}""".format(start=_SENTINEL_START, end=_SENTINEL_END)


def _upsert_instruction_block(project_path: str, filename: str) -> None:
    file_path = os.path.join(project_path, filename)
    try:
        if os.path.exists(file_path):
            with open(file_path) as f:
                content = f.read()
            if _SENTINEL_START in content and _SENTINEL_END in content:
                start_idx = content.index(_SENTINEL_START)
                end_idx = content.index(_SENTINEL_END) + len(_SENTINEL_END)
                content = content[:start_idx] + _AI_INSTRUCTION_BLOCK + content[end_idx:]
            else:
                content = content.rstrip() + "\n\n" + _AI_INSTRUCTION_BLOCK + "\n"
        else:
            content = _AI_INSTRUCTION_BLOCK + "\n"
        with open(file_path, "w") as f:
            f.write(content)
        print(f"Instructions written to {file_path}  ✓")
    except Exception as e:
        print(f"Warning: could not write {filename}: {e}", file=sys.stderr)


def _stdio_server_config(project_path: str, include_type: bool = False) -> dict:
    config = {"command": "code-outline-graph", "args": ["serve", "--no-watch", project_path]}
    if include_type:
        config["type"] = "stdio"
    return config


def _write_mcp_json_config(
    config_path: str,
    server_config: dict,
    label: str,
) -> None:
    try:
        os.makedirs(os.path.dirname(config_path), exist_ok=True)
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
        else:
            config = {}
        config.setdefault("mcpServers", {})
        config["mcpServers"]["code-outline"] = server_config
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"      Written: {config_path}  ✓")
    except Exception as e:
        print(f"      Warning: could not write {label}: {e}", file=sys.stderr)


def _write_project_mcp_config(project_path: str) -> None:
    _write_mcp_json_config(
        os.path.join(project_path, ".mcp.json"),
        _stdio_server_config(project_path),
        ".mcp.json",
    )


def _write_cursor_config(project_path: str) -> None:
    _write_mcp_json_config(
        os.path.join(project_path, ".cursor", "mcp.json"),
        _stdio_server_config(project_path, include_type=True),
        ".cursor/mcp.json",
    )


def _antigravity_mcp_config_path() -> str:
    return os.path.join(os.path.expanduser("~"), ".gemini", "antigravity", "mcp_config.json")


def _write_antigravity_config(project_path: str) -> None:
    _write_mcp_json_config(
        _antigravity_mcp_config_path(),
        _stdio_server_config(project_path),
        "Antigravity mcp_config.json",
    )


def _write_codex_config(project_path: str) -> None:
    codex_dir = os.path.join(project_path, ".codex")
    config_path = os.path.join(codex_dir, "config.toml")
    try:
        os.makedirs(codex_dir, exist_ok=True)
        entry = '[mcp_servers.code-outline]\ncommand = "code-outline-graph"\nargs = ["serve", "--no-watch"]\n'
        if os.path.exists(config_path):
            with open(config_path) as f:
                existing = f.read()
            if "[mcp_servers.code-outline]" in existing:
                print(f"Codex config already has code-outline entry: {config_path}")
                return
            content = existing.rstrip() + "\n\n" + entry
        else:
            content = entry
        with open(config_path, "w") as f:
            f.write(content)
        print(f"Codex MCP config written to {config_path}  ✓")
    except Exception as e:
        print(f"Warning: could not write .codex/config.toml: {e}", file=sys.stderr)


def _write_codex_hooks(project_path: str) -> None:
    codex_dir = os.path.join(project_path, ".codex")
    hooks_path = os.path.join(codex_dir, "hooks.json")
    update_cmd = "code-outline-graph update . 2>/dev/null; true"
    session_entry = {
        "hooks": [{"type": "command", "command": update_cmd, "timeout": 30}]
    }
    post_entry = {
        "matcher": "edit|write|apply",
        "hooks": [{"type": "command", "command": update_cmd, "timeout": 30}]
    }
    try:
        os.makedirs(codex_dir, exist_ok=True)
        if os.path.exists(hooks_path):
            with open(hooks_path) as f:
                config = json.load(f)
        else:
            config = {}
        config.setdefault("hooks", {})
        for event, entry in [("SessionStart", session_entry), ("PostToolUse", post_entry)]:
            config["hooks"].setdefault(event, [])
            already = any(
                any(hh.get("command", "").startswith("code-outline-graph update") for hh in h.get("hooks", []))
                for h in config["hooks"][event]
            )
            if not already:
                config["hooks"][event].append(entry)
        with open(hooks_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Codex hooks written to {hooks_path}  ✓")
    except Exception as e:
        print(f"Warning: could not write .codex/hooks.json: {e}", file=sys.stderr)


def _write_gemini_config(project_path: str) -> None:
    gemini_dir = os.path.join(project_path, ".gemini")
    config_path = os.path.join(gemini_dir, "settings.json")
    update_cmd = "code-outline-graph update . 2>/dev/null; true"
    session_entry = {
        "hooks": [{"type": "command", "command": update_cmd, "timeout": 30000}]
    }
    after_tool_entry = {
        "matcher": "write_.*|edit_.*|apply_.*",
        "hooks": [{"type": "command", "command": update_cmd, "timeout": 30000}]
    }
    try:
        os.makedirs(gemini_dir, exist_ok=True)
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
        else:
            config = {}
        config.setdefault("mcpServers", {})
        config["mcpServers"]["code-outline"] = {
            "command": "code-outline-graph",
            "args": ["serve", "--no-watch"],
        }
        config.setdefault("hooks", {})
        for event, entry in [("SessionStart", session_entry), ("AfterTool", after_tool_entry)]:
            config["hooks"].setdefault(event, [])
            already = any(
                any(hh.get("command", "").startswith("code-outline-graph update") for hh in h.get("hooks", []))
                for h in config["hooks"][event]
            )
            if not already:
                config["hooks"][event].append(entry)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Gemini MCP config + hooks written to {config_path}  ✓")
    except Exception as e:
        print(f"Warning: could not write .gemini/settings.json: {e}", file=sys.stderr)


def _write_claude_hooks(project_path: str) -> None:
    claude_dir = os.path.join(project_path, ".claude")
    config_path = os.path.join(claude_dir, "settings.json")
    update_cmd = "code-outline-graph update . 2>/dev/null; true"
    session_entry = {
        "matcher": "",
        "hooks": [{"type": "command", "command": update_cmd}]
    }
    post_edit_entry = {
        "matcher": "Edit|Write|MultiEdit|NotebookEdit",
        "hooks": [{"type": "command", "command": update_cmd}]
    }
    try:
        os.makedirs(claude_dir, exist_ok=True)
        if os.path.exists(config_path):
            with open(config_path) as f:
                config = json.load(f)
        else:
            config = {}
        config.setdefault("hooks", {})
        for event, entry in [("SessionStart", session_entry), ("PostToolUse", post_edit_entry)]:
            config["hooks"].setdefault(event, [])
            already = any(
                any(hh.get("command", "").startswith("code-outline-graph update") for hh in h.get("hooks", []))
                for h in config["hooks"][event]
            )
            if not already:
                config["hooks"][event].append(entry)
        with open(config_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"Claude Code hooks written to {config_path}  ✓")
    except Exception as e:
        print(f"Warning: could not write .claude/settings.json: {e}", file=sys.stderr)


def _get_db_indexer(project_path: str | None = None):
    from .db import Database
    from .indexer import Indexer

    resolved_project = resolve_project_path(project_path)
    db_path = ensure_project_db_path(resolved_project)
    db = Database(db_path)
    return db, Indexer(db), db_path


def _current_indexable_files(project_path: str, on_skip=None) -> set[str]:
    from .indexer import iter_indexable_files

    return {
        full
        for full, _language, _size, _mtime_ns in iter_indexable_files(
            project_path, on_skip=on_skip
        )
    }


def _show_embed_progress(indexer) -> None:
    """Render a live progress bar while the embedding thread runs."""
    if not (indexer._embed_thread and indexer._embed_thread.is_alive()):
        return

    BAR_WIDTH = 20
    term_width = shutil.get_terminal_size((80, 20)).columns

    print("\n[+] Waiting for symbol embeddings (semantic search)...")

    while indexer._embed_thread.is_alive():
        prog = indexer._embed_progress
        total = prog["total"]
        done = prog["done"]
        current = prog["current"]

        pct = done / total if total > 0 else 0
        filled = int(BAR_WIDTH * pct)
        bar = "█" * filled + "░" * (BAR_WIDTH - filled)
        suffix = f"  {current}" if current else ""
        line = f"\r[{bar}] {int(pct * 100):3d}%{suffix}"
        if len(line) > term_width:
            line = line[: term_width - 3] + "..."
        sys.stdout.write(line)
        sys.stdout.flush()
        time.sleep(0.1)

    bar = "█" * BAR_WIDTH
    sys.stdout.write(f"\r[{bar}] 100%{' ' * 30}\n")
    sys.stdout.flush()


def cmd_build(args):
    import time as _time

    path = resolve_project_path(args.path or ".")

    # Header box
    print("╔══════════════════════════════════════════════════════════╗")
    print("║         code-outline-graph  •  Building Index            ║")
    print("╚══════════════════════════════════════════════════════════╝")
    print()

    print(f"[1/7] Indexing {path} ...")
    _db, indexer, db_path = _get_db_indexer(path)

    _BAR_WIDTH = 20
    _term_width = max(40, shutil.get_terminal_size((120, 24)).columns - 1)
    _dir_stats = {}       # rel_dir -> {"files": int, "symbols": int}
    _start_time = _time.time()
    _live_stats = {"files": 0, "symbols": 0, "errors": 0}

    def _print_msg(msg):
        sys.stderr.write("\r" + " " * _term_width + "\r")  # clear bar line
        sys.stderr.write(msg + "\n")
        sys.stderr.flush()

    def _render_bar(file_path, live_stats):
        current = live_stats["files"]
        basename = os.path.basename(file_path) if file_path else ""
        elapsed = _time.time() - _start_time
        rate = f"{current / elapsed:.0f} files/s" if elapsed > 0 and current > 0 else "--"
        # Spinner instead of percentage — no pre-scan total needed
        spinner = "▏▎▍▌▋▊▉█▉▊▋▌▍▎"[current % 14]
        line = f"      [{spinner}] {current} files  {live_stats['symbols']} symbols  {rate}  →  {basename}"
        line = line[:_term_width]
        sys.stderr.write(line.ljust(_term_width) + "\r")
        sys.stderr.flush()

    def _on_file(full_path, symbol_count, elapsed_ms, error=None):
        d = os.path.dirname(full_path)
        rel = os.path.relpath(d, path)
        _dir_stats.setdefault(rel, {"files": 0, "symbols": 0})
        if error is None:
            _live_stats["files"] += 1
            _live_stats["symbols"] += symbol_count
            _dir_stats[rel]["files"] += 1
            _dir_stats[rel]["symbols"] += symbol_count
        else:
            _live_stats["errors"] += 1
            warn_msg = f"      WARN   {os.path.relpath(full_path, path):<40}  {error[:60]}"
            _print_msg(warn_msg)
        _render_bar(full_path, _live_stats)

    def _on_skip(full_path, reason):
        skip_msg = f"      SKIP   {os.path.relpath(full_path, path):<40}  ({reason})"
        _print_msg(skip_msg)
        _render_bar("", _live_stats)

    enable_embeddings = getattr(args, "embeddings", None)
    workers = getattr(args, "workers", None)
    background_large_files = getattr(args, "background_large_files", None)
    include = getattr(args, "include", None) or None
    exclude = getattr(args, "exclude", None) or None
    stats = indexer.index_project(
        path,
        on_file=_on_file,
        on_skip=_on_skip,
        embed=enable_embeddings,
        max_workers=workers,
        background_large_files=background_large_files,
        include=include,
        exclude=exclude,
    )

    # Print final completed bar (Done!)
    elapsed_index = _time.time() - _start_time
    bar = "█" * _BAR_WIDTH
    final_line = f"      [{bar}] Done!  {stats['files']} files  {stats['symbols']} symbols  {elapsed_index:.1f}s"
    final_line = final_line[:_term_width]
    sys.stderr.write(final_line.ljust(_term_width) + "\n")
    sys.stderr.flush()

    skipped_line = f"      Skipped: {stats['skipped']}  •  Errors: {stats.get('errors', 0)}  •  Time: {elapsed_index:.1f}s"
    if stats.get("large_deferred"):
        skipped_line += f"  •  Large files (background): {stats['large_deferred']}"
    if stats.get("large_skipped"):
        skipped_line += f"  •  Large files skipped: {stats['large_skipped']}"
    skipped_line += f"  •  Workers: {stats.get('workers', '?')}"
    print(skipped_line)

    # Dir summaries
    for rel_dir, ds in sorted(_dir_stats.items()):
        print(f"      {rel_dir:<20}  →  {ds['files']:>3} files   {ds['symbols']:>5} symbols")

    print(f"      DB: {db_path}")

    print("\n[2/7] Writing MCP configs (Claude/Cursor/Antigravity)...")
    _write_project_mcp_config(path)
    _write_cursor_config(path)
    _write_antigravity_config(path)

    print("\n[3/7] Writing Codex CLI config + hooks...")
    _write_codex_config(path)
    _write_codex_hooks(path)

    print("\n[4/7] Writing Gemini CLI config + hooks...")
    _write_gemini_config(path)

    print("\n[5/7] Writing Claude Code SessionStart + PostToolUse hooks...")
    _write_claude_hooks(path)

    print("\n[6/7] Writing AI instruction blocks (AGENTS.md, GEMINI.md)...")
    _upsert_instruction_block(path, "AGENTS.md")
    _upsert_instruction_block(path, "GEMINI.md")

    print("\n[7/7] Installing Claude Code skill...")
    cmd_install_skill(None)

    if stats.get("embeddings") == "enabled":
        _show_embed_progress(indexer)
        indexer.wait_for_embeddings()
    else:
        print("\n[+] Embeddings disabled (use --embeddings to enable semantic vectors)")

    # Footer box
    _total_elapsed = _time.time() - _start_time
    print()
    print("══════════════════════════════════════════════════════════")
    print(f"  Build complete in {_total_elapsed:.1f}s")
    print(f"  {stats['files']} files  •  {stats['symbols']} symbols  •  {stats['skipped']} skipped  •  {stats.get('errors', 0)} errors")
    print("══════════════════════════════════════════════════════════")


def cmd_update(args):
    path = resolve_project_path(args.path or ".")
    print(f"Updating index for {path}...")
    _db, indexer, _db_path = _get_db_indexer(path)
    from .indexer import iter_indexable_files

    updated = 0
    skipped = 0
    checked = 0
    errors = 0
    current_files: set[str] = set()

    def _on_skip(_full_path: str, _reason: str) -> None:
        nonlocal skipped
        skipped += 1

    include = getattr(args, "include", None) or None
    exclude = getattr(args, "exclude", None) or None
    for full, language, size, mtime_ns in iter_indexable_files(path, on_skip=_on_skip, include=include, exclude=exclude):
        current_files.add(full)
        try:
            if indexer.is_file_current(full, size, mtime_ns):
                skipped += 1
                continue
            indexer.index_file(full, language=language, file_size=size, mtime_ns=mtime_ns, embed=False)
            updated += 1
        except Exception as e:
            errors += 1
            print(f"Warning: failed to update {full}: {e}", file=sys.stderr)
        checked += 1
        if checked % 50 == 0:
            print(f"  checked {checked} files, {updated} updated...", end="\r", flush=True)
    if checked >= 50:
        print(" " * 60, end="\r")  # clear progress line
    pruned = indexer.prune_missing_files(current_files)
    print(f"Updated {updated} files, {skipped} unchanged, {pruned} pruned, {errors} errors")
    if updated > 0 and getattr(args, "embeddings", False):
        print("Updating embeddings...", end=" ", flush=True)
        indexer._batch_embed_all()
        print("done")
    elif updated > 0:
        print("Embeddings disabled (use --embeddings to update semantic vectors)")


def cmd_search(args):
    from .search import Searcher
    db, _indexer, _db_path = _get_db_indexer(args.project)
    results = Searcher(db).keyword_search(args.query, limit=args.limit)
    if args.kind:
        results = [r for r in results if r["kind"] == args.kind]
    if args.language:
        results = [r for r in results if r["language"] == args.language]
    if args.file:
        file_filter = os.path.abspath(os.path.join(resolve_project_path(args.project), args.file))
        results = [r for r in results if r["file_path"] == file_filter or args.file in r["file_path"]]
    if not results:
        print("No results.")
        return
    if args.json:
        print(json.dumps(results, indent=2))
        return
    for r in results:
        parent = f"  (in {r['parent_name']})" if r.get("parent_name") else ""
        print(f"{r['file_path']}:{r['start_line']}-{r['end_line']}  [{r['kind']}] {r['name']}{parent}")
        if r.get("signature"):
            print(f"  {r['signature']}")


def cmd_outline(args):
    if os.path.isabs(args.file):
        file_path = args.file
    else:
        project = resolve_project_path(getattr(args, 'project', '.'))
        file_path = os.path.abspath(os.path.join(project, args.file))
    db, indexer, _db_path = _get_db_indexer(args.project)
    indexer.ensure_fresh(file_path)
    symbols = db.get_symbols_by_file(file_path)
    if not symbols:
        print("No symbols found (file not indexed or no supported symbols).")
        return
    # Show imports and module-level variables first, then the rest
    header_kinds = ("import", "variable")
    header = [s for s in symbols if s.kind in header_kinds]
    body = [s for s in symbols if s.kind not in header_kinds]
    if header:
        print("--- imports / module-level ---")
        for s in header:
            print(f"{s.start_line}-{s.end_line}  [{s.kind}] {s.signature or s.name}")
        print()
    for s in body:
        indent = "  " if s.parent_name else ""
        print(f"{indent}{s.start_line}-{s.end_line}  [{s.kind}] {s.signature or s.name}")


def cmd_status(args):
    path = resolve_project_path(args.path or ".")
    db, _indexer, db_path = _get_db_indexer(path)
    row = db.conn.execute("SELECT COUNT(*) FROM indexed_files").fetchone()
    files = row[0] if row else 0
    row2 = db.conn.execute("SELECT COUNT(*) FROM symbols").fetchone()
    symbols = row2[0] if row2 else 0
    row3 = db.conn.execute("SELECT COUNT(*) FROM vec_symbols").fetchone()
    embeddings = row3[0] if row3 else 0
    stale = sum(1 for file_path in db.list_indexed_files() if not os.path.exists(file_path))
    languages = db.conn.execute(
        """
        SELECT language, COUNT(*) AS files
        FROM indexed_files
        GROUP BY language
        ORDER BY files DESC, language
        LIMIT 8
        """
    ).fetchall()
    print(f"Index: {files} files, {symbols} symbols")
    print(f"Embeddings: {embeddings}")
    print(f"Missing indexed files: {stale}")
    if languages:
        print("Languages: " + ", ".join(f"{r['language']}={r['files']}" for r in languages))
    print(f"Project: {path}")
    print(f"DB: {db_path}")


def cmd_prune(args):
    path = resolve_project_path(args.path or ".")
    _db, indexer, _db_path = _get_db_indexer(path)
    skipped = 0

    def _on_skip(_full_path: str, _reason: str) -> None:
        nonlocal skipped
        skipped += 1

    current_files = _current_indexable_files(path, on_skip=_on_skip)
    removed = indexer.prune_missing_files(current_files)
    print(f"Pruned {removed} files ({skipped} ignored/secret files skipped).")


def cmd_doctor(args):
    path = resolve_project_path(args.path or ".")
    db = None
    ok = True
    print(f"Project: {path}")
    print(f"Exists: {'yes' if os.path.isdir(path) else 'no'}")
    db_path = ensure_project_db_path(path)
    print(f"DB: {db_path}")
    try:
        from .db import Database
        db = Database(db_path)
        print("SQLite/sqlite-vec: ok")
    except Exception as e:
        ok = False
        print(f"SQLite/sqlite-vec: failed ({e})")
    try:
        from .parser import SymbolParser
        SymbolParser()._get_parser("python")
        print("tree-sitter python parser: ok")
    except Exception as e:
        ok = False
        print(f"tree-sitter python parser: failed ({e})")
    try:
        __import__("fastembed")
        print("embeddings: ok")
    except Exception as e:
        print(f"embeddings: unavailable ({e})")
    for rel in [".mcp.json", ".cursor/mcp.json", ".codex/config.toml", ".claude/settings.json", ".gemini/settings.json"]:
        config_path = os.path.join(path, rel)
        print(f"{rel}: {'found' if os.path.exists(config_path) else 'missing'}")
    if db is not None:
        stale = sum(1 for file_path in db.list_indexed_files() if not os.path.exists(file_path))
        print(f"Missing indexed files: {stale}")
        db.close()
    if not ok:
        sys.exit(1)


def cmd_install(args):
    path = resolve_project_path(args.path or ".")
    print(f"Installing MCP configs for {path} ...")

    print("\n[1/5] Writing MCP configs (Claude/Cursor/Antigravity)...")
    _write_project_mcp_config(path)
    _write_cursor_config(path)
    _write_antigravity_config(path)

    print("\n[2/5] Writing Codex CLI config + hooks...")
    _write_codex_config(path)
    _write_codex_hooks(path)

    print("\n[3/5] Writing Gemini CLI config + hooks...")
    _write_gemini_config(path)

    print("\n[4/5] Writing Claude Code SessionStart + PostToolUse hooks...")
    _write_claude_hooks(path)

    print("\n[5/5] Writing AI instruction blocks (AGENTS.md, GEMINI.md)...")
    _upsert_instruction_block(path, "AGENTS.md")
    _upsert_instruction_block(path, "GEMINI.md")

    print("\nInstall complete. Run 'code-outline-graph build .' to index symbols.")


def cmd_export(args):
    import csv
    import io
    path = resolve_project_path(getattr(args, "path", None) or ".")
    db, _indexer, _db_path = _get_db_indexer(path)
    rows = db.conn.execute(
        "SELECT id, name, kind, file_path, start_line, end_line, "
        "signature, docstring, parent_name, language FROM symbols ORDER BY file_path, start_line"
    ).fetchall()
    data = [dict(r) for r in rows]
    fmt = (args.format or "json").lower()
    if fmt == "json":
        text = json.dumps(data, indent=2)
    else:
        buf = io.StringIO()
        if data:
            writer = csv.DictWriter(buf, fieldnames=list(data[0].keys()))
            writer.writeheader()
            writer.writerows(data)
        text = buf.getvalue()
    output = getattr(args, "output", "-") or "-"
    if output != "-":
        with open(output, "w") as f:
            f.write(text)
        print(f"Exported {len(data)} symbols to {output}")
    else:
        print(text)


def cmd_callers(args):
    db, _indexer, _db_path = _get_db_indexer(getattr(args, "project", "."))
    results = db.get_callers(args.name)
    if getattr(args, "json", False):
        print(json.dumps(results, indent=2))
        return
    if not results:
        print(f"No callers found for '{args.name}'")
        return
    for r in results:
        print(f"{r['file_path']}:{r['call_line']}  [{r['kind']}] {r['name']}")


def cmd_callees(args):
    db, _indexer, _db_path = _get_db_indexer(getattr(args, "project", "."))
    results = db.get_callees(args.name)
    if getattr(args, "json", False):
        print(json.dumps(results, indent=2))
        return
    if not results:
        print(f"No callees found for '{args.name}'")
        return
    for r in results:
        print(f"line {r['call_line']}: calls '{r['callee_name']}'")


def cmd_install_skill(_args):
    import shutil
    skill_src_dir = os.path.join(os.path.dirname(__file__), "skill")
    if not os.path.isdir(skill_src_dir):
        print("Error: bundled skill directory not found in package.", file=sys.stderr)
        sys.exit(1)
    skill_dest_dir = os.path.expanduser("~/.claude/skills/code-outline-graph")
    os.makedirs(skill_dest_dir, exist_ok=True)
    for fname in os.listdir(skill_src_dir):
        src = os.path.join(skill_src_dir, fname)
        if os.path.isfile(src):
            shutil.copy2(src, os.path.join(skill_dest_dir, fname))
            print(f"Installed: {fname} → {skill_dest_dir}/  ✓")
    print(f"Skill installed to {skill_dest_dir}")


def cmd_serve(_args):
    import asyncio
    from .paths import project_db_path

    async def _run():
        from mcp.server.stdio import stdio_server
        from .server import app, configure_project, _get_components
        from . import server as server_mod
        from .watcher import CodeWatcher

        project = resolve_project_path(getattr(_args, "project", "."))
        configure_project(project)

        db_path = project_db_path(project)
        watch = getattr(_args, "watch", False)
        if os.path.exists(db_path) and watch:
            db, indexer, searcher = _get_components(project)
            server_mod._watcher = CodeWatcher(indexer, project)
            server_mod._watcher.start()

        async with stdio_server() as (r, w):
            await app.run(r, w, app.create_initialization_options())

    asyncio.run(_run())


def main():
    parser = argparse.ArgumentParser(
        prog="code-outline-graph",
        description="Symbol-level code indexer MCP server"
    )
    sub = parser.add_subparsers(dest="command")

    p_build = sub.add_parser("build", help="Index project and add to .mcp.json")
    p_build.add_argument("path", nargs="?", default=".", help="Project path (default: cwd)")
    p_build.add_argument(
        "--embeddings",
        action="store_true",
        default=None,
        help="Build semantic vector embeddings after indexing (default: off)",
    )
    p_build.add_argument(
        "--workers",
        type=int,
        help="Parser worker count (default: CODE_OUTLINE_INDEX_WORKERS or up to 4)",
    )
    p_build.add_argument(
        "--background-large-files",
        action="store_true",
        default=None,
        help="Index files >=512KB in the background (default: skip)",
    )
    p_build.add_argument("--include", action="append", metavar="GLOB",
        help="Only index files matching glob, e.g. 'src/**/*.py' (repeatable)")
    p_build.add_argument("--exclude", action="append", metavar="GLOB",
        help="Skip files matching glob, e.g. 'tests/*' (repeatable)")

    p_update = sub.add_parser("update", help="Reindex changed files only")
    p_update.add_argument("path", nargs="?", default=".", help="Project path (default: cwd)")
    p_update.add_argument(
        "--embeddings",
        action="store_true",
        help="Update semantic vector embeddings after changed files",
    )
    p_update.add_argument("--include", action="append", metavar="GLOB",
        help="Only reindex files matching glob (repeatable)")
    p_update.add_argument("--exclude", action="append", metavar="GLOB",
        help="Skip files matching glob (repeatable)")

    p_search = sub.add_parser("search", help="Search symbols by keyword")
    p_search.add_argument("--project", default=".", help="Project path (default: cwd)")
    p_search.add_argument("--kind", help="Filter by symbol kind")
    p_search.add_argument("--language", help="Filter by language")
    p_search.add_argument("--file", help="Filter by file path substring or relative path")
    p_search.add_argument("--limit", type=int, default=20, help="Maximum results (default: 20)")
    p_search.add_argument("--json", action="store_true", help="Emit JSON")
    p_search.add_argument("query", help="Search query")

    p_outline = sub.add_parser("outline", help="List symbols in a file")
    p_outline.add_argument("--project", default=".", help="Project path (default: cwd)")
    p_outline.add_argument("file", help="File path")

    p_status = sub.add_parser("status", help="Show index stats")
    p_status.add_argument("path", nargs="?", default=".", help="Project path")

    p_prune = sub.add_parser("prune", help="Remove stale index rows for deleted or ignored files")
    p_prune.add_argument("path", nargs="?", default=".", help="Project path")

    p_doctor = sub.add_parser("doctor", help="Check parser, DB, embedding, and MCP config health")
    p_doctor.add_argument("path", nargs="?", default=".", help="Project path")

    p_serve = sub.add_parser("serve", help="Start MCP server (stdio)")
    p_serve.add_argument("project", nargs="?", default=".", help="Project path (default: cwd)")
    p_serve.add_argument(
        "--watch",
        action="store_true",
        help="Watch files and update the index automatically",
    )
    p_serve.add_argument(
        "--no-watch",
        action="store_false",
        dest="watch",
        help="Disable file watching (default)",
    )
    p_serve.set_defaults(watch=False)

    p_install = sub.add_parser("install", help="Write MCP configs and hooks for a project (no reindex)")
    p_install.add_argument("path", nargs="?", default=".", help="Project path (default: cwd)")

    p_export = sub.add_parser("export", help="Export all indexed symbols to JSON or CSV")
    p_export.add_argument("path", nargs="?", default=".", help="Project path (default: cwd)")
    p_export.add_argument("--format", choices=["json", "csv"], default="json",
        help="Output format (default: json)")
    p_export.add_argument("--output", "-o", default="-",
        help="Output file path (default: stdout)")

    p_callers = sub.add_parser("callers", help="List all symbols that call the named function")
    p_callers.add_argument("name", help="Symbol name to find callers of")
    p_callers.add_argument("--project", default=".", help="Project path (default: cwd)")
    p_callers.add_argument("--json", action="store_true", help="Emit JSON")

    p_callees = sub.add_parser("callees", help="List all functions called by the named symbol")
    p_callees.add_argument("name", help="Symbol name to find callees of")
    p_callees.add_argument("--project", default=".", help="Project path (default: cwd)")
    p_callees.add_argument("--json", action="store_true", help="Emit JSON")

    sub.add_parser("install-skill", help="Install Claude Code skill to ~/.claude/skills/")

    args = parser.parse_args()

    if args.command == "build":
        cmd_build(args)
    elif args.command == "install":
        cmd_install(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "outline":
        cmd_outline(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "prune":
        cmd_prune(args)
    elif args.command == "doctor":
        cmd_doctor(args)
    elif args.command == "serve" or args.command is None:
        cmd_serve(args)
    elif args.command == "export":
        cmd_export(args)
    elif args.command == "callers":
        cmd_callers(args)
    elif args.command == "callees":
        cmd_callees(args)
    elif args.command == "install-skill":
        cmd_install_skill(args)
    else:
        parser.print_help()
