from __future__ import annotations

import os
import json
from itertools import islice
from mcp.server import Server
from mcp import types
from .db import Database
from .indexer import Indexer, iter_indexable_files
from .paths import ensure_project_db_path, resolve_project_path
from .search import Searcher
from .watcher import CodeWatcher

_db: Database | None = None
_indexer: Indexer | None = None
_searcher: Searcher | None = None
_watcher: CodeWatcher | None = None
_configured_project_path: str | None = None
_active_project_path: str | None = None


def _watch_enabled() -> bool:
    value = os.environ.get("CODE_OUTLINE_WATCH", "0")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def configure_project(project_path: str | None = None) -> None:
    global _configured_project_path
    _configured_project_path = resolve_project_path(project_path)


def _get_components(project_path: str | None = None):
    global _db, _indexer, _searcher, _active_project_path
    resolved_project = resolve_project_path(project_path or _configured_project_path)
    if _db is None or _active_project_path != resolved_project:
        if _db is not None:
            _db.conn.close()
        _db = Database(ensure_project_db_path(resolved_project))
        _indexer = Indexer(_db)
        _searcher = Searcher(_db)
        _active_project_path = resolved_project
    return _db, _indexer, _searcher


def _read_lines(file_path: str, start: int, end: int) -> str:
    start_idx = max(0, start - 1)
    end_idx = max(start_idx, end)
    with open(file_path, "r", errors="replace") as f:
        return "".join(islice(f, start_idx, end_idx))


app = Server("code-outline-graph")


@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="index_project", description="Index a project directory; pass watch=true to start file watcher",
            inputSchema={"type":"object","properties":{"path":{"type":"string"},"watch":{"type":"boolean"}},"required":["path"]}),
        types.Tool(name="list_outline", description="List all symbols in a file with line ranges",
            inputSchema={"type":"object","properties":{"file":{"type":"string"}},"required":["file"]}),
        types.Tool(name="get_symbol", description="Get symbol metadata by name",
            inputSchema={"type":"object","properties":{"name":{"type":"string"},"file":{"type":"string"}},"required":["name"]}),
        types.Tool(name="read_symbol_body", description="Read source lines for a symbol only",
            inputSchema={"type":"object","properties":{"name":{"type":"string"},"file":{"type":"string"}},"required":["name","file"]}),
        types.Tool(name="resolve_edit_target", description="NL description → top-5 symbol candidates (signatures only, no body)",
            inputSchema={"type":"object","properties":{"description":{"type":"string"}},"required":["description"]}),
        types.Tool(name="find_by_keyword", description="Keyword search across symbol names",
            inputSchema={"type":"object","properties":{"query":{"type":"string"}},"required":["query"]}),
        types.Tool(name="get_line_range", description="Read arbitrary line slice from a file",
            inputSchema={"type":"object","properties":{"file":{"type":"string"},"start":{"type":"integer"},"end":{"type":"integer"}},"required":["file","start","end"]}),
        types.Tool(name="get_outline_summary", description="Signatures only, ultra-compressed outline",
            inputSchema={"type":"object","properties":{"file":{"type":"string"}},"required":["file"]}),
        types.Tool(name="get_file_header",
            description="Get file header: shebang, imports, module docstring, top-level constants",
            inputSchema={"type":"object","properties":{"file":{"type":"string"}},"required":["file"]}),
        types.Tool(name="update_project", description="Reindex only changed files in the active project (faster than index_project)",
            inputSchema={"type":"object","properties":{"path":{"type":"string"}},"required":[]}),
        types.Tool(name="prune_project", description="Remove stale index rows for deleted or ignored files",
            inputSchema={"type":"object","properties":{"path":{"type":"string"}},"required":[]}),
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    if name == "index_project":
        global _watcher, _configured_project_path
        path = resolve_project_path(arguments["path"])
        _configured_project_path = path
        if _watcher:
            _watcher.stop()
            _watcher = None
        db, indexer, searcher = _get_components(path)
        stats = indexer.index_project(path)
        if arguments.get("watch", _watch_enabled()):
            _watcher = CodeWatcher(indexer, path)
            _watcher.start()
        return [types.TextContent(type="text", text=json.dumps(stats))]

    db, indexer, searcher = _get_components()

    if name == "list_outline":
        file_path = os.path.abspath(os.path.expanduser(arguments["file"]))
        indexer.ensure_fresh(file_path)
        symbols = db.get_symbols_by_file(file_path)
        result = [{"name":s.name,"kind":s.kind,"start_line":s.start_line,"end_line":s.end_line,"signature":s.signature,"parent_name":s.parent_name} for s in symbols]
        return [types.TextContent(type="text", text=json.dumps(result))]

    elif name == "get_symbol":
        file_arg = arguments.get("file")
        if file_arg:
            file_arg = os.path.abspath(os.path.expanduser(file_arg))
            indexer.ensure_fresh(file_arg)
        sym = db.get_symbol_by_name(arguments["name"], file_arg)
        if not sym:
            return [types.TextContent(type="text", text=json.dumps({"error":"not_found","name":arguments["name"]}))]
        return [types.TextContent(type="text", text=json.dumps({
            "name":sym.name,"kind":sym.kind,"file_path":sym.file_path,
            "start_line":sym.start_line,"end_line":sym.end_line,
            "signature":sym.signature,"docstring":sym.docstring,
            "parent_name":sym.parent_name,"language":sym.language
        }))]

    elif name == "read_symbol_body":
        file_path = os.path.abspath(os.path.expanduser(arguments["file"]))
        indexer.ensure_fresh(file_path)
        sym = db.get_symbol_by_name(arguments["name"], file_path)
        if not sym:
            return [types.TextContent(type="text", text=json.dumps({"error":"not_found","name":arguments["name"]}))]
        return [types.TextContent(type="text", text=_read_lines(file_path, sym.start_line, sym.end_line))]

    elif name == "resolve_edit_target":
        candidates = searcher.resolve_edit_target(arguments["description"])
        return [types.TextContent(type="text", text=json.dumps(candidates))]

    elif name == "find_by_keyword":
        results = searcher.keyword_search(arguments["query"])
        return [types.TextContent(type="text", text=json.dumps(results))]

    elif name == "get_line_range":
        file_path = os.path.abspath(os.path.expanduser(arguments["file"]))
        indexer.ensure_fresh(file_path)
        return [types.TextContent(type="text", text=_read_lines(file_path, int(arguments["start"]), int(arguments["end"])))]

    elif name == "get_outline_summary":
        file_path = os.path.abspath(os.path.expanduser(arguments["file"]))
        indexer.ensure_fresh(file_path)
        symbols = db.get_symbols_by_file(file_path)
        lines = [f"{s.start_line}-{s.end_line} [{s.kind}] {s.signature or s.name}" for s in symbols]
        return [types.TextContent(type="text", text="\n".join(lines))]

    elif name == "get_file_header":
        file_path = os.path.abspath(os.path.expanduser(arguments["file"]))
        indexer.ensure_fresh(file_path)
        symbols = db.get_symbols_by_file(file_path)
        header_syms = [s for s in symbols if s.kind in ("import", "variable") and s.start_line < 50]
        if not header_syms:
            # fallback: return first 20 lines
            body = _read_lines(file_path, 1, 20)
        else:
            last_line = max(s.end_line for s in header_syms)
            body = _read_lines(file_path, 1, last_line)
        return [types.TextContent(type="text", text=body)]

    elif name == "update_project":
        project_path = resolve_project_path(arguments.get("path") or _active_project_path)
        db, indexer, searcher = _get_components(project_path)
        updated = 0
        skipped = 0
        errors = 0
        current_files: set[str] = set()
        error_details: list[dict] = []

        def _on_skip(_full_path: str, _reason: str) -> None:
            nonlocal skipped
            skipped += 1

        for full, language, size, mtime_ns in iter_indexable_files(project_path, on_skip=_on_skip):
            current_files.add(full)
            try:
                if indexer.is_file_current(full, size, mtime_ns):
                    skipped += 1
                    continue
                indexer.index_file(full, language=language, file_size=size, mtime_ns=mtime_ns)
                updated += 1
            except Exception as e:
                errors += 1
                if len(error_details) < 10:
                    error_details.append({"file": full, "error": str(e)})
        pruned = indexer.prune_missing_files(current_files)
        return [types.TextContent(type="text", text=json.dumps({
            "updated": updated,
            "skipped": skipped,
            "pruned": pruned,
            "errors": errors,
            "error_details": error_details,
        }))]

    elif name == "prune_project":
        project_path = resolve_project_path(arguments.get("path") or _active_project_path)
        db, indexer, searcher = _get_components(project_path)
        current_files = {
            full
            for full, _language, _size, _mtime_ns in iter_indexable_files(project_path)
        }
        pruned = indexer.prune_missing_files(current_files)
        return [types.TextContent(type="text", text=json.dumps({"pruned": pruned}))]

    return [types.TextContent(type="text", text=json.dumps({"error":"unknown_tool","tool":name}))]


def main():
    from .cli import main as cli_main
    cli_main()


if __name__ == "__main__":
    main()
