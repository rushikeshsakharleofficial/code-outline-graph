import os
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
        return len(symbols)

    def index_project(self, project_path: str) -> dict:
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

        stats = {"files": 0, "symbols": 0, "skipped": 0}
        for root, dirs, files in os.walk(project_path):
            dirs[:] = [d for d in dirs if not d.startswith(".") and d not in (
                "node_modules", "__pycache__", ".git", "dist", "build", ".venv", "venv"
            )]
            for fname in files:
                full = os.path.join(root, fname)
                if matches(full):
                    stats["skipped"] += 1
                    continue
                if not detect_language(full):
                    continue
                try:
                    count = self.index_file(full)
                    stats["files"] += 1
                    stats["symbols"] += count
                except Exception:
                    stats["skipped"] += 1
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
