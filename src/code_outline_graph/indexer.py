import os
import time
import hashlib
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

    def index_file(self, file_path: str) -> int:
        """Parse and store symbols for one file. Returns symbol count."""
        checksum = compute_checksum(file_path)
        language = detect_language(file_path) or "unknown"
        symbols = self.parser.parse_file(file_path)
        for s in symbols:
            s.checksum = checksum
        self.db.insert_symbols(symbols, file_path, checksum, language)
        self._update_embeddings_for_file(file_path)
        return len(symbols)

    def _update_embeddings_for_file(self, file_path: str):
        """Update vec_symbols for symbols in one file. Lazy — skips if fastembed not available."""
        try:
            from .search import Searcher
            from .embeddings import Embedder
            searcher = Searcher(self.db)
            # Get only symbols for this file
            symbols = self.db.get_symbols_by_file(file_path)
            if not symbols:
                return
            from .embeddings import serialize_float32
            embedder = Embedder()
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
            pass  # embeddings are optional enhancement — never crash indexing

    def index_project(self, project_path: str, on_file=None, on_skip=None) -> dict:
        """Walk project directory and index all supported files."""
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
                    count = self.index_file(full)
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
