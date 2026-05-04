import json
from pathlib import Path
from types import SimpleNamespace

from code_outline_graph import cli


class FakeIndexer:
    def __init__(self):
        self.indexed_path = None
        self._embed_thread = None
        self._embed_progress = {"total": 0, "done": 0, "current": ""}

    def index_project(self, path, *_args, **_kwargs):
        self.indexed_path = path
        return {"files": 1, "symbols": 2, "skipped": 0}

    def wait_for_embeddings(self):
        pass


def test_build_uses_project_db_and_writes_project_aware_mcp_config(workspace_tmp, monkeypatch):
    fake_indexer = FakeIndexer()
    calls = {}

    def fake_get_db_indexer(project_path):
        calls["project_path"] = project_path
        return object(), fake_indexer, str(Path(project_path) / ".code-outline-graph" / "index.db")

    monkeypatch.setattr(cli, "_get_db_indexer", fake_get_db_indexer)
    monkeypatch.setattr(cli, "cmd_install_skill", lambda _args: None)

    cli.cmd_build(SimpleNamespace(path=str(workspace_tmp)))

    project_path = str(workspace_tmp)
    config = json.loads((workspace_tmp / ".mcp.json").read_text())

    assert calls["project_path"] == project_path
    assert fake_indexer.indexed_path == project_path
    assert config["mcpServers"]["code-outline"] == {
        "command": "code-outline-graph",
        "args": ["serve", project_path],
    }


def test_build_preserves_existing_mcp_servers(workspace_tmp, monkeypatch):
    (workspace_tmp / ".mcp.json").write_text(json.dumps({
        "mcpServers": {
            "other": {
                "command": "other-tool",
                "args": ["serve"],
            },
        },
    }))

    def fake_get_db_indexer(project_path):
        return object(), FakeIndexer(), str(Path(project_path) / ".code-outline-graph" / "index.db")

    monkeypatch.setattr(cli, "_get_db_indexer", fake_get_db_indexer)
    monkeypatch.setattr(cli, "cmd_install_skill", lambda _args: None)

    cli.cmd_build(SimpleNamespace(path=str(workspace_tmp)))

    config = json.loads((workspace_tmp / ".mcp.json").read_text())

    assert config["mcpServers"]["other"]["command"] == "other-tool"
    assert config["mcpServers"]["code-outline"]["args"] == ["serve", str(workspace_tmp)]
