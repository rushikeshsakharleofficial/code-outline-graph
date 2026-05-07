from __future__ import annotations

import concurrent.futures
import hashlib
import os
import threading
import time

from .db import Database
from .parser import SymbolParser, detect_language

_thread_local = threading.local()


def _get_thread_parser() -> SymbolParser:
    if not hasattr(_thread_local, "parser"):
        _thread_local.parser = SymbolParser()
    return _thread_local.parser


def compute_checksum(file_path: str) -> str:
    h = hashlib.blake2b(digest_size=16)
    with open(file_path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


_LARGE_FILE_THRESHOLD = 512 * 1024  # files >= 512 KB deferred to background
_SECRET_FILES = frozenset({".env", ".env.local", ".env.production", ".env.development"})
_SKIP_DIRS = frozenset({"node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"})


def file_metadata(file_path: str) -> tuple[int, int]:
    stat = os.stat(file_path)
    return stat.st_size, stat.st_mtime_ns


def _gitignore_matcher(project_path: str):
    try:
        import gitignore_parser

        gitignore_path = os.path.join(project_path, ".gitignore")
        if os.path.exists(gitignore_path):
            return gitignore_parser.parse_gitignore(gitignore_path)
    except ImportError:
        pass
    return lambda _p: False


def iter_indexable_files(project_path: str, on_skip=None):
    """Yield supported, non-ignored files with cached stat metadata."""
    matches = _gitignore_matcher(project_path)
    for root, dirs, files in os.walk(project_path):
        dirs[:] = [d for d in dirs if not d.startswith(".") and d not in _SKIP_DIRS]
        for fname in files:
            full = os.path.join(root, fname)
            if fname in _SECRET_FILES:
                if on_skip is not None:
                    on_skip(full, "secret file")
                continue
            if matches(full):
                if on_skip is not None:
                    on_skip(full, "gitignored")
                continue
            language = detect_language(full)
            if not language:
                continue
            try:
                size, mtime_ns = file_metadata(full)
            except OSError:
                continue
            yield full, language, size, mtime_ns


def _parse_for_index(
    file_path: str,
    language: str | None = None,
    file_size: int | None = None,
    mtime_ns: int | None = None,
):
    lang = language or detect_language(file_path) or "unknown"
    if file_size is None or mtime_ns is None:
        file_size, mtime_ns = file_metadata(file_path)

    t0 = time.time()
    if lang != "sqlite":
        source = open(file_path, "rb").read()
        checksum = hashlib.blake2b(source, digest_size=16).hexdigest()
        symbols = _get_thread_parser().parse_file(file_path, source=source)
    else:
        checksum = compute_checksum(file_path)
        symbols = _get_thread_parser().parse_file(file_path)
    for symbol in symbols:
        symbol.checksum = checksum
    elapsed_ms = (time.time() - t0) * 1000
    return symbols, checksum, lang, file_size, mtime_ns, elapsed_ms


class Indexer:
    def __init__(self, db: Database):
        self.db = db
        self.parser = SymbolParser()
        self._embedder = None  # lazy singleton, loaded once and reused
        self._embed_thread: threading.Thread | None = None
        self._large_file_thread: threading.Thread | None = None
        self._embed_progress: dict = {"total": 0, "done": 0, "current": ""}

    def _get_embedder(self):
        if self._embedder is None:
            from .embeddings import Embedder

            self._embedder = Embedder()
        return self._embedder

    def index_file(
        self,
        file_path: str,
        embed: bool = True,
        language: str | None = None,
        file_size: int | None = None,
        mtime_ns: int | None = None,
    ) -> int:
        """Parse and store symbols for one file. Returns symbol count."""
        if os.path.abspath(file_path) == os.path.abspath(self.db.path):
            return 0

        symbols, checksum, lang, file_size, mtime_ns, _elapsed_ms = _parse_for_index(
            file_path, language, file_size, mtime_ns
        )
        self.db.insert_symbols(symbols, file_path, checksum, lang, file_size, mtime_ns)
        if embed:
            self._update_embeddings_for_file(file_path)
        return len(symbols)

    def is_file_current(
        self, file_path: str, file_size: int | None = None, mtime_ns: int | None = None
    ) -> bool:
        """Use metadata fast path; fall back to checksum for older rows or touched files."""
        try:
            if file_size is None or mtime_ns is None:
                file_size, mtime_ns = file_metadata(file_path)
        except FileNotFoundError:
            self.db.delete_symbols_for_file(file_path)
            return True

        stored = self.db.get_indexed_file_state(file_path)
        if stored is None:
            return False
        if stored.get("file_size") == file_size and stored.get("mtime_ns") == mtime_ns:
            return True

        try:
            current = compute_checksum(file_path)
        except FileNotFoundError:
            self.db.delete_symbols_for_file(file_path)
            return True
        if stored.get("checksum") == current:
            self.db.update_indexed_file_metadata(file_path, file_size, mtime_ns)
            return True
        return False

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
                    [
                        (symbols[i].id, serialize_float32(vecs[i]))
                        for i in range(len(symbols))
                    ],
                )
                self.db.conn.commit()
        except Exception:
            pass  # embeddings are optional; never crash indexing

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
                self._embed_progress["current"] = os.path.basename(
                    chunk[0]["file_path"] or ""
                )
                texts = [
                    f"{r['name']} {r['signature'] or ''} {r['docstring'] or ''}".strip()
                    for r in chunk
                ]
                vecs = embedder.encode_batch(texts)
                with self.db._lock:
                    self.db.conn.executemany(
                        "INSERT OR REPLACE INTO vec_symbols (symbol_id, embedding) VALUES (?, ?)",
                        [
                            (chunk[j]["id"], serialize_float32(vecs[j]))
                            for j in range(len(chunk))
                        ],
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

    def prune_missing_files(self, current_files: set[str]) -> int:
        """Remove DB rows for indexed files no longer in the project walk."""
        removed = 0
        for file_path in self.db.list_indexed_files():
            if file_path not in current_files:
                self.db.delete_symbols_for_file(file_path)
                removed += 1
        return removed

    def index_project(self, project_path: str, on_file=None, on_skip=None) -> dict:
        """Walk project directory and index all supported files."""
        stats = {"files": 0, "symbols": 0, "skipped": 0, "unchanged": 0, "errors": 0}

        # Phase 1: walk serially; skip callbacks stay on main thread.
        indexable: list[tuple[str, str, int, int]] = []
        large_files: list[tuple[str, str, int, int]] = []
        current_files: set[str] = set()

        def _on_skip(full_path: str, reason: str) -> None:
            stats["skipped"] += 1
            if on_skip is not None:
                on_skip(full_path, reason)

        for item in iter_indexable_files(project_path, on_skip=_on_skip):
            _full, _language, size, _mtime_ns = item
            current_files.add(_full)
            if self.is_file_current(_full, size, _mtime_ns):
                stats["unchanged"] += 1
                continue
            if size >= _LARGE_FILE_THRESHOLD:
                large_files.append(item)
            else:
                indexable.append(item)

        stats["pruned"] = self.prune_missing_files(current_files)

        # Phase 2: parse normal files in parallel; no DB writes or lock contention.
        _cb_lock = threading.Lock()
        n_workers = min(32, (os.cpu_count() or 4) * 4)
        parse_results: list[tuple] = []

        def _parse_only(item: tuple[str, str, int, int]):
            file_path, language, size, mtime_ns = item
            return _parse_for_index(file_path, language, size, mtime_ns)

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as pool:
            future_map = {pool.submit(_parse_only, item): item for item in indexable}
            for fut in concurrent.futures.as_completed(future_map):
                full = future_map[fut][0]
                try:
                    symbols, checksum, lang, size, mtime_ns, elapsed_ms = fut.result()
                    parse_results.append((symbols, full, checksum, lang, size, mtime_ns))
                    stats["files"] += 1
                    stats["symbols"] += len(symbols)
                    if on_file is not None:
                        with _cb_lock:
                            on_file(full, len(symbols), elapsed_ms)
                except Exception as e:
                    stats["errors"] += 1
                    if on_file is not None:
                        with _cb_lock:
                            on_file(full, 0, 0, error=str(e))

        # Phase 3: bulk-write normal files; one FTS rebuild at the end.
        if parse_results:
            self.db.bulk_insert_all(parse_results)

        # Phase 4: large files index in background. Keep FTS triggers live to avoid
        # a second full FTS rebuild after the normal-file bulk insert.
        stats["large_deferred"] = len(large_files)
        if large_files:

            def _index_large_files():
                large_results = []
                for item in large_files:
                    fp = item[0]
                    try:
                        symbols, checksum, lang, size, mtime_ns, _ = _parse_only(item)
                        large_results.append((symbols, fp, checksum, lang, size, mtime_ns))
                    except Exception:
                        pass
                if large_results:
                    self.db.bulk_insert_all(large_results, rebuild_fts=False)

            if self._large_file_thread and self._large_file_thread.is_alive():
                self._large_file_thread.join(timeout=1)
            self._large_file_thread = threading.Thread(
                target=_index_large_files, daemon=True
            )
            self._large_file_thread.start()

        # Embed in background; do not block return on large codebases.
        if self._embed_thread and self._embed_thread.is_alive():
            self._embed_thread.join(timeout=1)
        self._embed_thread = threading.Thread(target=self._batch_embed_all, daemon=True)
        self._embed_thread.start()
        return stats

    def ensure_fresh(self, file_path: str):
        """Check freshness; reindex synchronously if stale."""
        try:
            size, mtime_ns = file_metadata(file_path)
        except FileNotFoundError:
            self.db.delete_symbols_for_file(file_path)
            return
        if not self.is_file_current(file_path, size, mtime_ns):
            self.index_file(file_path, file_size=size, mtime_ns=mtime_ns)
