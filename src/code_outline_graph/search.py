from typing import Optional
from .db import Database


class Searcher:
    def __init__(self, db: Database):
        self.db = db
        self._embedder = None

    def fts_search(self, query: str, limit: int = 10) -> list[dict]:
        """FTS5 BM25 search. Returns metadata only, no body."""
        try:
            rows = self.db.conn.execute("""
                SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
                       s.signature, s.docstring, s.parent_name, s.language
                FROM symbols_fts
                JOIN symbols s ON symbols_fts.rowid = s.id
                WHERE symbols_fts MATCH ?
                ORDER BY rank
                LIMIT ?
            """, (query, limit)).fetchall()
        except Exception:
            return []
        return [dict(r) for r in rows]

    def keyword_search(self, query: str, limit: int = 20) -> list[dict]:
        """LIKE-based keyword search on name and file_path."""
        pattern = f"%{query}%"
        rows = self.db.conn.execute("""
            SELECT id, name, kind, file_path, start_line, end_line,
                   signature, docstring, parent_name, language
            FROM symbols
            WHERE name LIKE ? OR file_path LIKE ?
            ORDER BY name
            LIMIT ?
        """, (pattern, pattern, limit)).fetchall()
        return [dict(r) for r in rows]

    def index_embeddings(self, embedder=None) -> int:
        """Embed all symbols and store in vec_symbols."""
        if embedder is None:
            if self._embedder is None:
                from .embeddings import Embedder
                self._embedder = Embedder()
            embedder = self._embedder

        rows = self.db.conn.execute(
            "SELECT id, name, signature, docstring FROM symbols"
        ).fetchall()
        if not rows:
            return 0

        texts = [
            f"{r['name']} {r['signature'] or ''} {r['docstring'] or ''}".strip()
            for r in rows
        ]
        from .embeddings import serialize_float32
        vecs = embedder.encode_batch(texts)

        self.db.conn.execute("DELETE FROM vec_symbols")
        self.db.conn.executemany(
            "INSERT OR REPLACE INTO vec_symbols (symbol_id, embedding) VALUES (?, ?)",
            [(rows[i]["id"], serialize_float32(vecs[i])) for i in range(len(rows))]
        )
        self.db.conn.commit()
        return len(rows)

    def vec_search(self, query: str, embedder=None, limit: int = 10) -> list[dict]:
        """Vector similarity search."""
        if embedder is None:
            if self._embedder is None:
                from .embeddings import Embedder
                self._embedder = Embedder()
            embedder = self._embedder

        from .embeddings import serialize_float32
        qvec = embedder.encode(query)
        try:
            rows = self.db.conn.execute("""
                SELECT s.id, s.name, s.kind, s.file_path, s.start_line, s.end_line,
                       s.signature, s.docstring, s.parent_name, s.language,
                       v.distance
                FROM vec_symbols v
                JOIN symbols s ON v.symbol_id = s.id
                WHERE v.embedding MATCH ?
                ORDER BY v.distance
                LIMIT ?
            """, (serialize_float32(qvec), limit)).fetchall()
        except Exception:
            return []
        return [dict(r) for r in rows]

    def resolve_edit_target(self, description: str, limit: int = 5) -> list[dict]:
        """
        Hybrid FTS5 + sqlite-vec with RRF merge.
        Returns candidates with metadata only — no body.
        """
        fts = self.fts_search(description, limit=limit * 2)

        vec = []
        try:
            vec = self.vec_search(description, limit=limit * 2)
        except Exception:
            pass

        # RRF: score = 1/(60 + rank)
        scores: dict[int, float] = {}
        for rank, r in enumerate(fts):
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0 / (60 + rank)
        for rank, r in enumerate(vec):
            scores[r["id"]] = scores.get(r["id"], 0.0) + 1.0 / (60 + rank)

        all_candidates = {r["id"]: r for r in (fts + vec)}
        ranked = sorted(all_candidates.values(), key=lambda r: -scores.get(r["id"], 0.0))

        return [
            {
                "name": r["name"], "kind": r["kind"], "file_path": r["file_path"],
                "start_line": r["start_line"], "end_line": r["end_line"],
                "signature": r["signature"], "docstring": r.get("docstring"),
                "parent_name": r.get("parent_name"), "language": r["language"],
            }
            for r in ranked[:limit]
        ]
