import argparse
import json
import os
import sys

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
        print(f"Instructions written to {file_path}")
    except Exception as e:
        print(f"Warning: could not write {filename}: {e}", file=sys.stderr)


def _write_codex_config(project_path: str) -> None:
    codex_dir = os.path.join(project_path, ".codex")
    config_path = os.path.join(codex_dir, "config.toml")
    try:
        os.makedirs(codex_dir, exist_ok=True)
        entry = '[mcp_servers.code-outline]\ncommand = "code-outline-graph"\nargs = ["serve"]\n'
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
        print(f"Codex MCP config written to {config_path}")
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
        print(f"Codex hooks written to {hooks_path}")
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
        config["mcpServers"]["code-outline"] = {"command": "code-outline-graph", "args": ["serve"]}
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
        print(f"Gemini MCP config + hooks written to {config_path}")
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
        print(f"Claude Code hooks written to {config_path}")
    except Exception as e:
        print(f"Warning: could not write .claude/settings.json: {e}", file=sys.stderr)


def _get_db_indexer(project_path: str | None = None):
    from .db import Database
    from .indexer import Indexer

    resolved_project = resolve_project_path(project_path)
    db_path = ensure_project_db_path(resolved_project)
    db = Database(db_path)
    return db, Indexer(db), db_path


def cmd_build(args):
    path = resolve_project_path(args.path or ".")

    print(f"\n[1/7] Indexing {path}...")
    _db, indexer, db_path = _get_db_indexer(path)
    stats = indexer.index_project(path)
    print(f"      Done: {stats['files']} files, {stats['symbols']} symbols, {stats['skipped']} skipped")
    print(f"      DB: {db_path}")

    print("\n[2/7] Writing Claude Code / Cursor MCP config (.mcp.json)...")
    mcp_path = os.path.join(path, ".mcp.json")
    try:
        if os.path.exists(mcp_path):
            with open(mcp_path) as f:
                config = json.load(f)
        else:
            config = {}
        config.setdefault("mcpServers", {})
        config["mcpServers"]["code-outline"] = {"command": "code-outline-graph", "args": ["serve", path]}
        with open(mcp_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"      Written: {mcp_path}")
    except Exception as e:
        print(f"      Warning: could not write .mcp.json: {e}", file=sys.stderr)

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

    print("\nBuild complete. All AI clients configured.")


def cmd_update(args):
    path = resolve_project_path(args.path or ".")
    print(f"Updating index for {path}...")
    db, indexer, _db_path = _get_db_indexer(path)
    from .parser import detect_language
    from .indexer import compute_checksum
    updated = 0
    skipped = 0
    for root, dirs, files in os.walk(path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
            "node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"
        )]
        for fname in files:
            full = os.path.join(root, fname)
            if fname in (".env", ".env.local", ".env.production", ".env.development"):
                skipped += 1
                continue
            if not detect_language(full):
                continue
            try:
                current = compute_checksum(full)
                stored = db.get_indexed_checksum(full)
                if stored != current:
                    indexer.index_file(full)
                    updated += 1
                else:
                    skipped += 1
            except Exception:
                pass
    print(f"Updated {updated} files, {skipped} unchanged")


def cmd_search(args):
    from .search import Searcher
    db, _indexer, _db_path = _get_db_indexer(args.project)
    results = Searcher(db).keyword_search(args.query, limit=20)
    if not results:
        print("No results.")
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
    print(f"Index: {files} files, {symbols} symbols")
    print(f"Project: {path}")
    print(f"DB: {db_path}")


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
            print(f"Installed: {fname} → {skill_dest_dir}/")
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
        if os.path.exists(db_path):
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

    p_update = sub.add_parser("update", help="Reindex changed files only")
    p_update.add_argument("path", nargs="?", default=".", help="Project path (default: cwd)")

    p_search = sub.add_parser("search", help="Search symbols by keyword")
    p_search.add_argument("--project", default=".", help="Project path (default: cwd)")
    p_search.add_argument("query", help="Search query")

    p_outline = sub.add_parser("outline", help="List symbols in a file")
    p_outline.add_argument("--project", default=".", help="Project path (default: cwd)")
    p_outline.add_argument("file", help="File path")

    p_status = sub.add_parser("status", help="Show index stats")
    p_status.add_argument("path", nargs="?", default=".", help="Project path")

    p_serve = sub.add_parser("serve", help="Start MCP server (stdio)")
    p_serve.add_argument("project", nargs="?", default=".", help="Project path (default: cwd)")

    sub.add_parser("install-skill", help="Install Claude Code skill to ~/.claude/skills/")

    args = parser.parse_args()

    if args.command == "build":
        cmd_build(args)
    elif args.command == "update":
        cmd_update(args)
    elif args.command == "search":
        cmd_search(args)
    elif args.command == "outline":
        cmd_outline(args)
    elif args.command == "status":
        cmd_status(args)
    elif args.command == "serve" or args.command is None:
        cmd_serve(args)
    elif args.command == "install-skill":
        cmd_install_skill(args)
    else:
        parser.print_help()
