"""
LegalPlus Knowledge Base — Keyword Search (Step 1 of RAG pipeline)

This script performs a simple keyword search on the `chunks` table
(no embeddings, no LLM yet) to validate that the knowledge base is
usable before adding vector search or LLM-based answer generation.

Usage:
    python search_kb.py
"""

import os
from typing import Optional
import psycopg2
import psycopg2.extras
from pydantic import BaseModel, Field
from dotenv import load_dotenv

load_dotenv()


# --- Data model (Pydantic) ---
# Using Pydantic here even for a simple script: it documents exactly
# what a "search result" looks like, and validates the shape of data
# coming out of the database before it's used anywhere else.
class ChunkResult(BaseModel):
    chunk_id: str
    doc_id: Optional[str] = None
    article_number: Optional[str] = None
    article_label: Optional[str] = None
    text_raw: str
    word_count: Optional[int] = None


# --- Database connection ---
def get_connection():
    """
    Reads connection details from environment variables (.env file).
    Expected variables:
        KB_DB_HOST (default: localhost)
        KB_DB_PORT (default: 5432)
        KB_DB_NAME (default: legalplus)
        KB_DB_USER (default: postgres)
        KB_DB_PASSWORD (required)
    """
    return psycopg2.connect(
        host=os.getenv("KB_DB_HOST", "localhost"),
        port=os.getenv("KB_DB_PORT", "5432"),
        dbname=os.getenv("KB_DB_NAME", "legalplus"),
        user=os.getenv("KB_DB_USER", "postgres"),
        password=os.getenv("KB_DB_PASSWORD"),
    )


# --- Keyword search ---
def search_chunks(query: str, limit: int = 5) -> list[ChunkResult]:
    """
    Simple case-insensitive keyword search on chunks.text_raw.
    No embeddings involved — this is the baseline to validate
    before adding vector similarity search later.
    """
    sql = """
        SELECT chunk_id, doc_id, article_number, article_label, text_raw, word_count
        FROM chunks
        WHERE LOWER(text_raw) LIKE LOWER(%s)
        ORDER BY word_count DESC NULLS LAST
        LIMIT %s;
    """
    pattern = f"%{query}%"

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (pattern, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    # Validate each row through the Pydantic model before returning it
    return [ChunkResult(**row) for row in rows]


def print_results(results: list[ChunkResult]) -> None:
    if not results:
        print("Aucun résultat trouvé pour cette recherche.")
        return

    print(f"\n{len(results)} résultat(s) trouvé(s) :\n")
    for i, chunk in enumerate(results, start=1):
        print(f"--- Résultat {i} ---")
        print(f"Article : {chunk.article_label or chunk.article_number or 'N/A'}")
        print(f"Doc ID  : {chunk.doc_id or 'N/A'}")
        print(f"Texte   : {chunk.text_raw[:400]}{'...' if len(chunk.text_raw) > 400 else ''}")
        print()


def main():
    print("=" * 60)
    print("Recherche dans la base de connaissances LegalPlus (mots-clés)")
    print("=" * 60)

    while True:
        query = input("\nVotre question (ou 'quit' pour sortir) : ").strip()
        if query.lower() in ("quit", "exit", "q"):
            break
        if not query:
            continue

        try:
            results = search_chunks(query, limit=5)
            print_results(results)
        except Exception as e:
            print(f"Erreur lors de la recherche : {e}")


if __name__ == "__main__":
    main()
