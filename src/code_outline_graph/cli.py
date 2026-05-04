import argparse
import json
import os
import sys

from .paths import ensure_project_db_path, resolve_project_path


def _get_db_indexer(project_path: str | None = None):
    from .db import Database
    from .indexer import Indexer

    resolved_project = resolve_project_path(project_path)
    db_path = ensure_project_db_path(resolved_project)
    db = Database(db_path)
    return db, Indexer(db), db_path


def cmd_build(args):
    path = resolve_project_path(args.path or ".")
    print(f"Indexing {path}...")
    _db, indexer, db_path = _get_db_indexer(path)
    stats = indexer.index_project(path)
    print(f"Done: {stats['files']} files, {stats['symbols']} symbols, {stats['skipped']} skipped")
    print(f"DB: {db_path}")

    # Auto-add to .mcp.json in the project root
    mcp_path = os.path.join(path, ".mcp.json")
    try:
        if os.path.exists(mcp_path):
            with open(mcp_path) as f:
                config = json.load(f)
        else:
            config = {}

        config.setdefault("mcpServers", {})
        config["mcpServers"]["code-outline"] = {
            "command": "code-outline-graph",
            "args": ["serve", path]
        }

        with open(mcp_path, "w") as f:
            json.dump(config, f, indent=2)
        print(f"MCP config written to {mcp_path}")
    except Exception as e:
        print(f"Warning: could not write .mcp.json: {e}", file=sys.stderr)


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
    else:
        parser.print_help()
