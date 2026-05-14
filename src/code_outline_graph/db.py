import os
import sqlite3
import threading
import time
from dataclasses import dataclass
from typing import Optional

import sqlite_vec


def _load_sqlite_vec(conn: sqlite3.Connection) -> None:
    conn.enable_load_extension(True)
    try:
        sqlite_vec.load(conn)
    finally:
        conn.enable_load_extension(False)


@dataclass
class Symbol:
    name: str
    kind: str
    file_path: str
    start_line: int
    end_line: int
    signature: Optional[str]
    docstring: Optional[str]
    parent_name: Optional[str]
    parent_id: Optional[int]
    language: str
    checksum: str
    id: Optional[int] = None


def _sqlite_cache_kb() -> int:
    raw = os.environ.get("CODE_OUTLINE_SQLITE_CACHE_MB")
    if raw:
        try:
            return max(1, int(raw)) * 1024
        except ValueError:
            pass
    return 65536  # 64 MB default


def _sqlite_mmap_bytes() -> int:
    raw = os.environ.get("CODE_OUTLINE_SQLITE_MMAP_MB")
    if raw:
        try:
            return max(0, int(raw)) * 1024 * 1024
        except ValueError:
            pass
    return 268435456  # 256 MB default


class Database:
    def __init__(self, path: str) -> None:
        self.path = path
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
        self.conn.execute(f"PRAGMA cache_size=-{_sqlite_cache_kb()}")
        self.conn.execute(f"PRAGMA mmap_size={_sqlite_mmap_bytes()}")
        self.conn.execute("PRAGMA temp_store=memory")
        self.conn.row_factory = sqlite3.Row
        _load_sqlite_vec(self.conn)
        self._create_schema()

    def _create_schema(self) -> None:
        self.conn.executescript("""
            CREATE TABLE IF NOT EXISTS symbols (
                id          INTEGER PRIMARY KEY,
                name        TEXT NOT NULL,
                kind        TEXT NOT NULL,
                file_path   TEXT NOT NULL,
                start_line  INTEGER NOT NULL,
                end_line    INTEGER NOT NULL,
                signature   TEXT,
                docstring   TEXT,
                parent_name TEXT,
                parent_id   INTEGER,
                language    TEXT NOT NULL,
                checksum    TEXT NOT NULL,
                indexed_at  INTEGER NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_symbols_file      ON symbols(file_path);
            CREATE INDEX IF NOT EXISTS idx_symbols_name      ON symbols(name);
            CREATE INDEX IF NOT EXISTS idx_symbols_file_line ON symbols(file_path, start_line);
            CREATE INDEX IF NOT EXISTS idx_symbols_name_file ON symbols(name, file_path);
            CREATE INDEX IF NOT EXISTS idx_symbols_parent    ON symbols(parent_id);

            CREATE VIRTUAL TABLE IF NOT EXISTS symbols_fts USING fts5(
                name, kind, file_path, signature, docstring,
                content='symbols', content_rowid='id',
                tokenize='porter unicode61'
            );

            CREATE VIRTUAL TABLE IF NOT EXISTS vec_symbols USING vec0(
                symbol_id   INTEGER PRIMARY KEY,
                embedding   FLOAT[384]
            );

            CREATE TABLE IF NOT EXISTS indexed_files (
                file_path     TEXT PRIMARY KEY,
                checksum      TEXT NOT NULL,
                git_head      TEXT,
                symbol_count  INTEGER,
                language      TEXT,
                file_size     INTEGER,
                mtime_ns      INTEGER,
                indexed_at    INTEGER NOT NULL
            );

            CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
              INSERT INTO symbols_fts(rowid, name, kind, file_path, signature, docstring)
              VALUES (new.id, new.name, new.kind, new.file_path, new.signature, new.docstring);
            END;

            CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
              INSERT INTO symbols_fts(symbols_fts, rowid, name, kind, file_path, signature, docstring)
              VALUES ('delete', old.id, old.name, old.kind, old.file_path, old.signature, old.docstring);
            END;

            CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
              INSERT INTO symbols_fts(symbols_fts, rowid, name, kind, file_path, signature, docstring)
              VALUES ('delete', old.id, old.name, old.kind, old.file_path, old.signature, old.docstring);
              INSERT INTO symbols_fts(rowid, name, kind, file_path, signature, docstring)
              VALUES (new.id, new.name, new.kind, new.file_path, new.signature, new.docstring);
            END;
        """)
        self._ensure_indexed_files_columns()
        self.conn.commit()

    def _ensure_indexed_files_columns(self) -> None:
        columns = {
            row["name"]
            for row in self.conn.execute("PRAGMA table_info(indexed_files)").fetchall()
        }
        if "file_size" not in columns:
            self.conn.execute("ALTER TABLE indexed_files ADD COLUMN file_size INTEGER")
        if "mtime_ns" not in columns:
            self.conn.execute("ALTER TABLE indexed_files ADD COLUMN mtime_ns INTEGER")

    def insert_symbols(
        self,
        symbols: list[Symbol],
        file_path: str,
        checksum: str,
        language: str,
        file_size: Optional[int] = None,
        mtime_ns: Optional[int] = None,
    ) -> None:
        with self._lock:
            now = int(time.time())
            with self.conn:
                # subquery delete avoids a separate SELECT + dynamic IN clause
                self.conn.execute(
                    "DELETE FROM vec_symbols WHERE symbol_id IN (SELECT id FROM symbols WHERE file_path=?)",
                    (file_path,),
                )
                self.conn.execute("DELETE FROM symbols WHERE file_path=?", (file_path,))
                self.conn.executemany(
                    """
                    INSERT INTO symbols
                        (name, kind, file_path, start_line, end_line,
                         signature, docstring, parent_name, parent_id,
                         language, checksum, indexed_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    [
                        (
                            sym.name, sym.kind, sym.file_path,
                            sym.start_line, sym.end_line, sym.signature,
                            sym.docstring, sym.parent_name, sym.parent_id,
                            sym.language, sym.checksum, now,
                        )
                        for sym in symbols
                    ],
                )
                self._upsert_indexed_file(
                    file_path, checksum, len(symbols), language, now, file_size, mtime_ns
                )

    _TRIGGER_SQL = """
        CREATE TRIGGER IF NOT EXISTS symbols_ai AFTER INSERT ON symbols BEGIN
          INSERT INTO symbols_fts(rowid, name, kind, file_path, signature, docstring)
          VALUES (new.id, new.name, new.kind, new.file_path, new.signature, new.docstring);
        END;
        CREATE TRIGGER IF NOT EXISTS symbols_ad AFTER DELETE ON symbols BEGIN
          INSERT INTO symbols_fts(symbols_fts, rowid, name, kind, file_path, signature, docstring)
          VALUES ('delete', old.id, old.name, old.kind, old.file_path, old.signature, old.docstring);
        END;
        CREATE TRIGGER IF NOT EXISTS symbols_au AFTER UPDATE ON symbols BEGIN
          INSERT INTO symbols_fts(symbols_fts, rowid, name, kind, file_path, signature, docstring)
          VALUES ('delete', old.id, old.name, old.kind, old.file_path, old.signature, old.docstring);
          INSERT INTO symbols_fts(rowid, name, kind, file_path, signature, docstring)
          VALUES (new.id, new.name, new.kind, new.file_path, new.signature, new.docstring);
        END;
    """

    def bulk_insert_all(
        self,
        file_results: list[tuple],
        chunk_size: int = 2000,
        rebuild_fts: bool = True,
    ) -> None:
        """Write all parsed results as fast as possible.

        When rebuild_fts is true, disables FTS triggers during inserts, commits
        in chunks to bound memory, then rebuilds FTS once and recreates triggers.
        """
        if not file_results:
            return
        with self._lock:
            if rebuild_fts:
                self.conn.execute("DROP TRIGGER IF EXISTS symbols_ai")
                self.conn.execute("DROP TRIGGER IF EXISTS symbols_ad")
                self.conn.execute("DROP TRIGGER IF EXISTS symbols_au")
                self.conn.commit()
            try:
                now = int(time.time())
                for i in range(0, len(file_results), chunk_size):
                    chunk = file_results[i : i + chunk_size]
                    with self.conn:
                        for result in chunk:
                            symbols, file_path, checksum, language, file_size, mtime_ns = (
                                self._unpack_file_result(result)
                            )
                            self._replace_file_symbols(
                                symbols, file_path, checksum, language, now, file_size, mtime_ns
                            )
                if rebuild_fts:
                    self.conn.execute("INSERT INTO symbols_fts(symbols_fts) VALUES('rebuild')")
                self.conn.commit()
            finally:
                if rebuild_fts:
                    self.conn.executescript(self._TRIGGER_SQL)
                    self.conn.commit()

    @staticmethod
    def _unpack_file_result(result: tuple) -> tuple:
        if len(result) == 4:
            symbols, file_path, checksum, language = result
            return symbols, file_path, checksum, language, None, None
        return result

    def _replace_file_symbols(
        self,
        symbols: list[Symbol],
        file_path: str,
        checksum: str,
        language: str,
        now: int,
        file_size: Optional[int],
        mtime_ns: Optional[int],
    ) -> None:
        self.conn.execute(
            "DELETE FROM vec_symbols WHERE symbol_id IN "
            "(SELECT id FROM symbols WHERE file_path=?)",
            (file_path,),
        )
        self.conn.execute("DELETE FROM symbols WHERE file_path=?", (file_path,))
        if symbols:
            self.conn.executemany(
                "INSERT INTO symbols (name, kind, file_path, start_line,"
                " end_line, signature, docstring, parent_name, parent_id,"
                " language, checksum, indexed_at)"
                " VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                [
                    (
                        s.name, s.kind, s.file_path,
                        s.start_line, s.end_line, s.signature,
                        s.docstring, s.parent_name, s.parent_id,
                        s.language, s.checksum, now,
                    )
                    for s in symbols
                ],
            )
        self._upsert_indexed_file(
            file_path, checksum, len(symbols), language, now, file_size, mtime_ns
        )

    def _upsert_indexed_file(
        self,
        file_path: str,
        checksum: str,
        symbol_count: int,
        language: str,
        now: int,
        file_size: Optional[int],
        mtime_ns: Optional[int],
    ) -> None:
        self.conn.execute(
            """
            INSERT INTO indexed_files
                (file_path, checksum, git_head, symbol_count, language,
                 file_size, mtime_ns, indexed_at)
            VALUES (?, ?, NULL, ?, ?, ?, ?, ?)
            ON CONFLICT(file_path) DO UPDATE SET
                checksum     = excluded.checksum,
                symbol_count = excluded.symbol_count,
                language     = excluded.language,
                file_size    = excluded.file_size,
                mtime_ns     = excluded.mtime_ns,
                indexed_at   = excluded.indexed_at
            """,
            (file_path, checksum, symbol_count, language, file_size, mtime_ns, now),
        )

    def delete_symbols_for_file(self, file_path: str) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    "DELETE FROM vec_symbols WHERE symbol_id IN "
                    "(SELECT id FROM symbols WHERE file_path = ?)",
                    (file_path,),
                )
                self.conn.execute(
                    "DELETE FROM symbols WHERE file_path = ?",
                    (file_path,),
                )
                self.conn.execute(
                    "DELETE FROM indexed_files WHERE file_path = ?",
                    (file_path,),
                )

    def list_indexed_files(self) -> list[str]:
        rows = self.conn.execute(
            "SELECT file_path FROM indexed_files ORDER BY file_path"
        ).fetchall()
        return [row["file_path"] for row in rows]

    def get_symbols_by_file(self, file_path: str) -> list[Symbol]:
        rows = self.conn.execute(
            """
            SELECT id, name, kind, file_path, start_line, end_line,
                   signature, docstring, parent_name, parent_id,
                   language, checksum
            FROM symbols
            WHERE file_path = ?
            ORDER BY start_line
            """,
            (file_path,),
        ).fetchall()
        return [
            Symbol(
                id=row["id"],
                name=row["name"],
                kind=row["kind"],
                file_path=row["file_path"],
                start_line=row["start_line"],
                end_line=row["end_line"],
                signature=row["signature"],
                docstring=row["docstring"],
                parent_name=row["parent_name"],
                parent_id=row["parent_id"],
                language=row["language"],
                checksum=row["checksum"],
            )
            for row in rows
        ]

    def get_symbol_by_name(
        self, name: str, file_path: Optional[str] = None
    ) -> Optional[Symbol]:
        if file_path is not None:
            row = self.conn.execute(
                """
                SELECT id, name, kind, file_path, start_line, end_line,
                       signature, docstring, parent_name, parent_id,
                       language, checksum
                FROM symbols
                WHERE name = ? AND file_path = ?
                LIMIT 1
                """,
                (name, file_path),
            ).fetchone()
        else:
            row = self.conn.execute(
                """
                SELECT id, name, kind, file_path, start_line, end_line,
                       signature, docstring, parent_name, parent_id,
                       language, checksum
                FROM symbols
                WHERE name = ?
                LIMIT 1
                """,
                (name,),
            ).fetchone()
        if row is None:
            return None
        return Symbol(
            id=row["id"],
            name=row["name"],
            kind=row["kind"],
            file_path=row["file_path"],
            start_line=row["start_line"],
            end_line=row["end_line"],
            signature=row["signature"],
            docstring=row["docstring"],
            parent_name=row["parent_name"],
            parent_id=row["parent_id"],
            language=row["language"],
            checksum=row["checksum"],
        )

    def load_all_indexed_file_states(self) -> dict:
        """Load all indexed_files rows into a dict keyed by file_path. One query instead of N."""
        rows = self.conn.execute(
            "SELECT file_path, checksum, file_size, mtime_ns FROM indexed_files"
        ).fetchall()
        return {row["file_path"]: dict(row) for row in rows}

    def get_indexed_checksum(self, file_path: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT checksum FROM indexed_files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return row["checksum"] if row is not None else None

    def get_indexed_file_state(self, file_path: str) -> Optional[dict]:
        row = self.conn.execute(
            """
            SELECT checksum, file_size, mtime_ns
            FROM indexed_files
            WHERE file_path = ?
            """,
            (file_path,),
        ).fetchone()
        return dict(row) if row is not None else None

    def update_indexed_file_metadata(
        self, file_path: str, file_size: int, mtime_ns: int
    ) -> None:
        with self._lock:
            with self.conn:
                self.conn.execute(
                    """
                    UPDATE indexed_files
                    SET file_size = ?, mtime_ns = ?
                    WHERE file_path = ?
                    """,
                    (file_size, mtime_ns, file_path),
                )

    def close(self) -> None:
        with self._lock:
            self.conn.close()
