from __future__ import annotations

import os
import time
import hashlib
import threading
from .db import Database
from .parser import SymbolParser, detect_language


def compute_checksum(file_path: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


class Indexer:
    def __init__(self, db: Database):
        self.db = db
        self.parser = SymbolParser()
        self._embedder = None  # lazy singleton — loaded once, reused
        self._embed_thread: threading.Thread | None = None
        self._embed_progress: dict = {"total": 0, "done": 0, "current": ""}

    def _get_embedder(self):
        if self._embedder is None:
            from .embeddings import Embedder
            self._embedder = Embedder()
        return self._embedder

    def index_file(self, file_path: str, embed: bool = True) -> int:
        """Parse and store symbols for one file. Returns symbol count."""
        checksum = compute_checksum(file_path)
        language = detect_language(file_path) or "unknown"
        symbols = self.parser.parse_file(file_path)
        for s in symbols:
            s.checksum = checksum
        self.db.insert_symbols(symbols, file_path, checksum, language)
        if embed:
            self._update_embeddings_for_file(file_path)
        return len(symbols)

    def _update_embeddings_for_file(self, file_path: str):
        """Update vec_symbols for one file using shared embedder singleton."""
        try:
            from .embeddings import serialize_float32
            symbols = self.db.get_symbols_by_file(file_path)
            if not symbols:
                return
            embedder = self._get_embedder()
            texts = [
                f"{s.name} {s.signature or ''} {s.docstring or ''}".strip()
                for s in symbols
            ]
            vecs = embedder.encode_batch(texts)
            with self.db._lock:
                self.db.conn.executemany(
                    "INSERT OR REPLACE INTO vec_symbols (symbol_id, embedding) VALUES (?, ?)",
                    [(symbols[i].id, serialize_float32(vecs[i])) for i in range(len(symbols))]
                )
                self.db.conn.commit()
        except Exception:
            pass  # embeddings are optional — never crash indexing

    def _batch_embed_all(self):
        """Embed symbols that are missing embeddings. Safe to run concurrently."""
        try:
            try:
                os.nice(15)
            except (AttributeError, OSError):
                pass
            from .embeddings import serialize_float32
            embedder = self._get_embedder()
            rows = self.db.conn.execute(
                "SELECT s.id, s.name, s.signature, s.docstring, s.file_path FROM symbols s "
                "LEFT JOIN vec_symbols v ON v.symbol_id = s.id "
                "WHERE v.symbol_id IS NULL"
            ).fetchall()
            if not rows:
                return
            total = len(rows)
            self._embed_progress["total"] = total
            self._embed_progress["done"] = 0
            chunk_size = 32
            for i in range(0, total, chunk_size):
                chunk = rows[i : i + chunk_size]
                self._embed_progress["current"] = os.path.basename(chunk[0]["file_path"] or "")
                texts = [
                    f"{r['name']} {r['signature'] or ''} {r['docstring'] or ''}".strip()
                    for r in chunk
                ]
                vecs = embedder.encode_batch(texts)
                with self.db._lock:
                    self.db.conn.executemany(
                        "INSERT OR REPLACE INTO vec_symbols (symbol_id, embedding) VALUES (?, ?)",
                        [(chunk[j]["id"], serialize_float32(vecs[j])) for j in range(len(chunk))]
                    )
                    self.db.conn.commit()
                self._embed_progress["done"] = min(i + chunk_size, total)
            self._embed_progress["done"] = total
            self._embed_progress["current"] = ""
        except Exception:
            pass

    def wait_for_embeddings(self) -> None:
        """Block until any background embedding thread completes."""
        if self._embed_thread and self._embed_thread.is_alive():
            self._embed_thread.join()

    def index_project(self, project_path: str, on_file=None, on_skip=None) -> dict:
        """Walk project directory and index all supported files."""
        try:
            os.nice(10)  # lower priority — don't spike user's CPU
        except (AttributeError, OSError):
            pass  # Windows or permission denied

        try:
            import gitignore_parser
            gitignore_path = os.path.join(project_path, ".gitignore")
            if os.path.exists(gitignore_path):
                matches = gitignore_parser.parse_gitignore(gitignore_path)
            else:
                matches = lambda p: False
        except ImportError:
            matches = lambda p: False

        stats = {"files": 0, "symbols": 0, "skipped": 0, "errors": 0}
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                "node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"
            )]
            for fname in files:
                full = os.path.join(root, fname)
                if fname in (".env", ".env.local", ".env.production", ".env.development"):
                    stats["skipped"] += 1
                    if on_skip is not None:
                        on_skip(full, "secret file")
                    continue
                if matches(full):
                    stats["skipped"] += 1
                    if on_skip is not None:
                        on_skip(full, "gitignored")
                    continue
                if not detect_language(full):
                    continue
                t0 = time.time()
                try:
                    # embed=False: skip per-file embedding; batch at end instead
                    count = self.index_file(full, embed=False)
                    elapsed_ms = (time.time() - t0) * 1000
                    stats["files"] += 1
                    stats["symbols"] += count
                    if on_file is not None:
                        on_file(full, count, elapsed_ms)
                except Exception as e:
                    elapsed_ms = (time.time() - t0) * 1000
                    stats["errors"] += 1
                    if on_file is not None:
                        on_file(full, 0, elapsed_ms, error=str(e))

        # Embed in background — don't block return on large codebases
        if self._embed_thread and self._embed_thread.is_alive():
            self._embed_thread.join(timeout=1)
        self._embed_thread = threading.Thread(target=self._batch_embed_all, daemon=True)
        self._embed_thread.start()
        return stats

    def ensure_fresh(self, file_path: str):
        """Check checksum; reindex synchronously if stale. Core freshness guarantee."""
        try:
            current = compute_checksum(file_path)
        except FileNotFoundError:
            self.db.delete_symbols_for_file(file_path)
            return
        stored = self.db.get_indexed_checksum(file_path)
        if stored != current:
            self.index_file(file_path)
