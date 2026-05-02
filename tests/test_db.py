import pytest

from code_outline_graph import db


class FakeConnection:
    def __init__(self):
        self.enable_calls = []
        self.row_factory = None

    def enable_load_extension(self, enabled):
        self.enable_calls.append(enabled)

    def executescript(self, _sql):
        pass

    def commit(self):
        pass


def test_database_temporarily_enables_extension_loading(monkeypatch):
    conn = FakeConnection()
    load_calls = []

    monkeypatch.setattr(db.sqlite3, "connect", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(db.sqlite_vec, "load", lambda loaded_conn: load_calls.append(loaded_conn))

    db.Database("index.db")

    assert conn.enable_calls == [True, False]
    assert load_calls == [conn]


def test_database_disables_extension_loading_when_load_fails(monkeypatch):
    conn = FakeConnection()

    def fail_load(_conn):
        raise RuntimeError("load failed")

    monkeypatch.setattr(db.sqlite3, "connect", lambda *_args, **_kwargs: conn)
    monkeypatch.setattr(db.sqlite_vec, "load", fail_load)

    with pytest.raises(RuntimeError, match="load failed"):
        db.Database("index.db")

    assert conn.enable_calls == [True, False]
