import warnings
from pathlib import Path

from code_outline_graph import embeddings as embeddings_mod
from code_outline_graph import indexer as indexer_mod
from code_outline_graph.indexer import Indexer, iter_indexable_files
from code_outline_graph.server import _read_lines


class FreshnessDB:
    path = "index.db"

    def __init__(self, state):
        self.state = state
        self.updated = []
        self.deleted = []

    def get_indexed_file_state(self, _file_path):
        return self.state

    def update_indexed_file_metadata(self, file_path, file_size, mtime_ns):
        self.updated.append((file_path, file_size, mtime_ns))

    def delete_symbols_for_file(self, file_path):
        self.deleted.append(file_path)


class ProjectIndexDB(FreshnessDB):
    def __init__(self, state):
        super().__init__(state)
        self.bulk_calls = []

    def bulk_insert_all(self, results, rebuild_fts=True):
        self.bulk_calls.append((results, rebuild_fts))


def test_is_file_current_skips_checksum_when_metadata_matches(monkeypatch):
    db = FreshnessDB({"checksum": "old", "file_size": 12, "mtime_ns": 34})
    indexer = Indexer(db)

    def fail_checksum(_file_path):
        raise AssertionError("checksum should not run when metadata matches")

    monkeypatch.setattr(indexer_mod, "compute_checksum", fail_checksum)

    assert indexer.is_file_current("app.py", 12, 34) is True
    assert db.updated == []


def test_is_file_current_updates_metadata_when_checksum_matches(monkeypatch):
    db = FreshnessDB({"checksum": "same", "file_size": 1, "mtime_ns": 2})
    indexer = Indexer(db)

    monkeypatch.setattr(indexer_mod, "compute_checksum", lambda _file_path: "same")

    assert indexer.is_file_current("app.py", 12, 34) is True
    assert db.updated == [("app.py", 12, 34)]


def test_iter_indexable_files_honors_gitignore_and_secret_files(workspace_tmp):
    (workspace_tmp / ".gitignore").write_text("ignored.py\n")
    (workspace_tmp / "ignored.py").write_text("def ignored():\n    pass\n")
    (workspace_tmp / "kept.py").write_text("def kept():\n    pass\n")
    (workspace_tmp / ".env").write_text("TOKEN=secret\n")

    skipped = []
    files = list(
        iter_indexable_files(
            str(workspace_tmp),
            on_skip=lambda path, reason: skipped.append((Path(path).name, reason)),
        )
    )

    assert {Path(path).name for path, *_rest in files} == {"kept.py"}
    assert ("ignored.py", "gitignored") in skipped
    assert (".env", "secret file") in skipped


def test_read_lines_streams_requested_range(workspace_tmp):
    path = workspace_tmp / "large.py"
    path.write_text("".join(f"line {i}\n" for i in range(1, 11)))

    assert _read_lines(str(path), 3, 5) == "line 3\nline 4\nline 5\n"


def test_quiet_hf_output_suppresses_progress_bar_warning():
    with warnings.catch_warnings():
        embeddings_mod._quiet_hf_output()
        assert any(
            action == "ignore" and pattern and "HF_HUB_DISABLE_PROGRESS_BARS=1" in pattern.pattern
            for action, pattern, _category, _module, _lineno in warnings.filters
        )


def test_index_project_skips_unchanged_files_without_parsing(monkeypatch, workspace_tmp):
    path = workspace_tmp / "app.py"
    path.write_text("def kept():\n    pass\n")

    db = ProjectIndexDB({"checksum": "old", "file_size": path.stat().st_size, "mtime_ns": path.stat().st_mtime_ns})
    indexer = Indexer(db)

    monkeypatch.setattr(
        indexer_mod,
        "iter_indexable_files",
        lambda _project_path, on_skip=None: iter(
            [(str(path), "python", path.stat().st_size, path.stat().st_mtime_ns)]
        ),
    )
    monkeypatch.setattr(
        indexer_mod,
        "_parse_for_index",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("unchanged file should not parse")),
    )
    monkeypatch.setattr(Indexer, "_batch_embed_all", lambda self: None)

    stats = indexer.index_project(str(workspace_tmp))
    indexer.wait_for_embeddings()

    assert stats["files"] == 0
    assert stats["symbols"] == 0
    assert stats["unchanged"] == 1
    assert db.bulk_calls == []
