"""Store and search vectors using PostgreSQL + pgvector (exact cosine search, no ANN index)."""
from typing import Any

import psycopg

from .config import FILTERABLE
from .models import Chunk

TABLE = "chunks"


def _vec(v: list[float]) -> str:
    return "[" + ",".join(f"{x:.7f}" for x in v) + "]"


class PgVectorStore:
    def __init__(self, database_url: str, dimensions: int) -> None:
        if not database_url:
            raise ValueError("DATABASE_URL is empty (copy starter/.env.example to starter/.env)")
        if dimensions <= 0:
            raise ValueError("dimensions must be positive")
        self.database_url = database_url
        self.dimensions = dimensions

    def _connect(self) -> psycopg.Connection:
        return psycopg.connect(self.database_url, connect_timeout=5)

    def create_schema(self) -> None:
        """Create the table if needed and refuse to mix vectors of a different dimension."""
        with self._connect() as conn:
            conn.execute("CREATE EXTENSION IF NOT EXISTS vector")
            conn.execute(f"""
                CREATE TABLE IF NOT EXISTS {TABLE} (
                    strategy        TEXT NOT NULL,
                    chunk_id        TEXT NOT NULL,
                    document_id     TEXT NOT NULL,
                    source          TEXT NOT NULL,
                    page            INTEGER NOT NULL,
                    chapter         TEXT,
                    section         TEXT,
                    section_title   TEXT,
                    page_type       TEXT,
                    char_start      INTEGER,
                    char_end        INTEGER,
                    text            TEXT NOT NULL,
                    content_hash    TEXT NOT NULL,
                    embedding_model TEXT NOT NULL,
                    embedding       vector({self.dimensions}) NOT NULL,
                    ingested_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
                    PRIMARY KEY (strategy, chunk_id)
                )""")
            conn.execute(f"CREATE INDEX IF NOT EXISTS {TABLE}_filter_idx ON {TABLE} (strategy, chapter)")
            dim = conn.execute(
                "SELECT atttypmod FROM pg_attribute WHERE attrelid = %s::regclass AND attname = 'embedding'",
                (TABLE,)).fetchone()[0]
            if dim != self.dimensions:
                raise ValueError(f"table has vector({dim}) but model produces {self.dimensions} dims")

    def existing_hashes(self, strategy: str, document_id: str) -> dict[str, tuple[str, str]]:
        """chunk_id -> (content_hash, embedding_model) currently stored."""
        with self._connect() as conn:
            rows = conn.execute(
                f"SELECT chunk_id, content_hash, embedding_model FROM {TABLE} WHERE strategy=%s AND document_id=%s",
                (strategy, document_id)).fetchall()
        return {r[0]: (r[1], r[2]) for r in rows}

    def upsert(self, strategy: str, chunks: list[Chunk], vectors: list[list[float] | None],
               model_name: str, document_id: str) -> dict[str, int]:
        """Write stable chunk IDs without duplicates and remove obsolete chunks of the document.

        `vectors[i]` may be None for a chunk whose content_hash and model are unchanged
        (it is then left untouched). Everything happens in one transaction.
        """
        if len(chunks) != len(vectors):
            raise ValueError(f"{len(chunks)} chunks but {len(vectors)} vectors")
        ids = [c.chunk_id for c in chunks]
        if len(set(ids)) != len(ids):
            raise ValueError("duplicate chunk_id in input")
        stats = {"written": 0, "unchanged": 0, "deleted": 0}
        with self._connect() as conn, conn.transaction():
            for chunk, vector in zip(chunks, vectors):
                if vector is None:
                    stats["unchanged"] += 1
                    continue
                if len(vector) != self.dimensions:
                    raise ValueError(f"{chunk.chunk_id}: vector has {len(vector)} dims, expected {self.dimensions}")
                m = chunk.metadata
                conn.execute(f"""
                    INSERT INTO {TABLE} (strategy, chunk_id, document_id, source, page, chapter, section,
                        section_title, page_type, char_start, char_end, text, content_hash, embedding_model, embedding)
                    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s::vector)
                    ON CONFLICT (strategy, chunk_id) DO UPDATE SET
                        document_id=EXCLUDED.document_id, source=EXCLUDED.source, page=EXCLUDED.page,
                        chapter=EXCLUDED.chapter, section=EXCLUDED.section, section_title=EXCLUDED.section_title,
                        page_type=EXCLUDED.page_type, char_start=EXCLUDED.char_start, char_end=EXCLUDED.char_end,
                        text=EXCLUDED.text, content_hash=EXCLUDED.content_hash,
                        embedding_model=EXCLUDED.embedding_model, embedding=EXCLUDED.embedding, ingested_at=now()
                    """, (strategy, chunk.chunk_id, chunk.document_id, chunk.source, chunk.page,
                          m.get("chapter"), m.get("section"), m.get("section_title"), m.get("page_type"),
                          m.get("char_start"), m.get("char_end"), chunk.text, m["content_hash"],
                          model_name, _vec(vector)))
                stats["written"] += 1
            cur = conn.execute(
                f"DELETE FROM {TABLE} WHERE strategy=%s AND document_id=%s AND NOT (chunk_id = ANY(%s))",
                (strategy, document_id, ids))
            stats["deleted"] = cur.rowcount
        return stats

    def search(self, strategy: str, query_vector: list[float], top_k: int = 3,
               filters: dict[str, Any] | None = None) -> list[dict[str, Any]]:
        """Filter whitelisted metadata in SQL, rank by cosine distance, return top-k with metadata."""
        if len(query_vector) != self.dimensions:
            raise ValueError(f"query vector has {len(query_vector)} dims, expected {self.dimensions}")
        where, params = ["strategy = %s"], [strategy]
        for key, value in (filters or {}).items():
            if key not in FILTERABLE:
                raise ValueError(f"filter field {key!r} not allowed; use one of {FILTERABLE}")
            where.append(f"{key} = %s")
            params.append(value)
        qv = _vec(query_vector)
        sql = f"""
            SELECT chunk_id, document_id, source, page, chapter, section, section_title, page_type,
                   char_start, char_end, text, 1 - (embedding <=> %s::vector) AS score
            FROM {TABLE} WHERE {' AND '.join(where)}
            ORDER BY embedding <=> %s::vector LIMIT %s"""
        with self._connect() as conn:
            cur = conn.execute(sql, [qv, *params, qv, top_k])
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, row)) for row in cur.fetchall()]

    def counts(self) -> dict[str, dict[str, int]]:
        """Row count and duplicate-position count per strategy (for the re-ingest check)."""
        with self._connect() as conn:
            rows = conn.execute(f"SELECT strategy, count(*), count(DISTINCT chunk_id) FROM {TABLE} GROUP BY strategy ORDER BY strategy").fetchall()
            dups = dict(conn.execute(f"""
                SELECT strategy, count(*) FROM (
                    SELECT strategy FROM {TABLE} GROUP BY strategy, document_id, page, char_start, content_hash
                    HAVING count(*) > 1) d GROUP BY strategy""").fetchall())
        return {r[0]: {"rows": r[1], "distinct_ids": r[2], "duplicate_positions": dups.get(r[0], 0)} for r in rows}
