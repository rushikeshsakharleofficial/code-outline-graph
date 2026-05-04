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


class Database:
    def __init__(self, path: str) -> None:
        self.conn = sqlite3.connect(path, check_same_thread=False)
        self._lock = threading.RLock()
        self.conn.execute("PRAGMA journal_mode=WAL")
        self.conn.execute("PRAGMA synchronous=NORMAL")
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
            CREATE INDEX IF NOT EXISTS idx_symbols_file ON symbols(file_path);
            CREATE INDEX IF NOT EXISTS idx_symbols_name ON symbols(name);

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
        self.conn.commit()

    def insert_symbols(
        self,
        symbols: list[Symbol],
        file_path: str,
        checksum: str,
        language: str,
    ) -> None:
        with self._lock:
            now = int(time.time())
            with self.conn:
                # delete vec_symbols first (foreign key order)
                ids = [row[0] for row in self.conn.execute("SELECT id FROM symbols WHERE file_path=?", (file_path,)).fetchall()]
                if ids:
                    placeholders = ",".join("?" * len(ids))
                    self.conn.execute(f"DELETE FROM vec_symbols WHERE symbol_id IN ({placeholders})", ids)
                self.conn.execute("DELETE FROM symbols WHERE file_path=?", (file_path,))
                for sym in symbols:
                    self.conn.execute(
                        """
                        INSERT INTO symbols
                            (name, kind, file_path, start_line, end_line,
                             signature, docstring, parent_name, parent_id,
                             language, checksum, indexed_at)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            sym.name,
                            sym.kind,
                            sym.file_path,
                            sym.start_line,
                            sym.end_line,
                            sym.signature,
                            sym.docstring,
                            sym.parent_name,
                            sym.parent_id,
                            sym.language,
                            sym.checksum,
                            now,
                        ),
                    )
                self.conn.execute(
                    """
                    INSERT INTO indexed_files
                        (file_path, checksum, git_head, symbol_count, language, indexed_at)
                    VALUES (?, ?, NULL, ?, ?, ?)
                    ON CONFLICT(file_path) DO UPDATE SET
                        checksum     = excluded.checksum,
                        symbol_count = excluded.symbol_count,
                        language     = excluded.language,
                        indexed_at   = excluded.indexed_at
                    """,
                    (file_path, checksum, len(symbols), language, now),
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

    def get_indexed_checksum(self, file_path: str) -> Optional[str]:
        row = self.conn.execute(
            "SELECT checksum FROM indexed_files WHERE file_path = ?",
            (file_path,),
        ).fetchone()
        return row["checksum"] if row is not None else None

    def close(self) -> None:
        with self._lock:
            self.conn.close()
