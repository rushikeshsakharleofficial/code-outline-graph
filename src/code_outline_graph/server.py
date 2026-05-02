import os
import json
from mcp.server import Server
from mcp.server.stdio import stdio_server
from mcp import types
from .db import Database
from .indexer import Indexer
from .search import Searcher
from .watcher import CodeWatcher

_db: Database | None = None
_indexer: Indexer | None = None
_searcher: Searcher | None = None
_watcher: CodeWatcher | None = None

DEFAULT_DB = os.path.expanduser("~/.code-outline-graph/index.db")


def _get_components():
    global _db, _indexer, _searcher
    if _db is None:
        os.makedirs(os.path.dirname(DEFAULT_DB), exist_ok=True)
        _db = Database(DEFAULT_DB)
        _indexer = Indexer(_db)
        _searcher = Searcher(_db)
    return _db, _indexer, _searcher


def _read_lines(file_path: str, start: int, end: int) -> str:
    with open(file_path, "r", errors="replace") as f:
        lines = f.readlines()
    return "".join(lines[start - 1:end])


app = Server("code-outline-graph")


@app.list_tools()
async def list_tools():
    return [
        types.Tool(name="index_project", description="Index a project directory and start file watcher",
            inputSchema={"type":"object","properties":{"path":{"type":"string"}},"required":["path"]}),
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
    ]


@app.call_tool()
async def call_tool(name: str, arguments: dict):
    db, indexer, searcher = _get_components()

    if name == "index_project":
        path = os.path.expanduser(arguments["path"])
        global _watcher
        stats = indexer.index_project(path)
        if _watcher:
            _watcher.stop()
        _watcher = CodeWatcher(indexer, path)
        _watcher.start()
        return [types.TextContent(type="text", text=json.dumps(stats))]

    elif name == "list_outline":
        file_path = os.path.expanduser(arguments["file"])
        indexer.ensure_fresh(file_path)
        symbols = db.get_symbols_by_file(file_path)
        result = [{"name":s.name,"kind":s.kind,"start_line":s.start_line,"end_line":s.end_line,"signature":s.signature,"parent_name":s.parent_name} for s in symbols]
        return [types.TextContent(type="text", text=json.dumps(result))]

    elif name == "get_symbol":
        file_arg = arguments.get("file")
        if file_arg:
            file_arg = os.path.expanduser(file_arg)
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
        file_path = os.path.expanduser(arguments["file"])
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
        file_path = os.path.expanduser(arguments["file"])
        indexer.ensure_fresh(file_path)
        return [types.TextContent(type="text", text=_read_lines(file_path, int(arguments["start"]), int(arguments["end"])))]

    elif name == "get_outline_summary":
        file_path = os.path.expanduser(arguments["file"])
        indexer.ensure_fresh(file_path)
        symbols = db.get_symbols_by_file(file_path)
        lines = [f"{s.start_line}-{s.end_line} [{s.kind}] {s.signature or s.name}" for s in symbols]
        return [types.TextContent(type="text", text="\n".join(lines))]

    return [types.TextContent(type="text", text=json.dumps({"error":"unknown_tool","tool":name}))]


def main():
    import asyncio
    asyncio.run(_run())


async def _run():
    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


if __name__ == "__main__":
    main()
