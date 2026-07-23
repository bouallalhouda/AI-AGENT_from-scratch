"""
LegalPlus Knowledge Base — Embed Missing Chunks

Finds every row in `chunks` where embedding IS NULL (e.g. the rows
just inserted by ingest_law_articles.py) and computes their embedding
with OpenAI's text-embedding-3-small — the same model already used
for your existing ~5300 chunks, so everything stays comparable.

Usage:
    python embed_missing_chunks.py

Requires in .env:
    OPENAI_API_KEY=sk-...
    KB_DB_HOST, KB_DB_PORT, KB_DB_NAME, KB_DB_USER, KB_DB_PASSWORD
"""

import os
import time
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"
BATCH_SIZE = 50  # OpenAI allows batching multiple texts per call

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


def get_connection():
    return psycopg2.connect(
        host=os.getenv("KB_DB_HOST", "localhost"),
        port=os.getenv("KB_DB_PORT", "5432"),
        dbname=os.getenv("KB_DB_NAME", "legalplus"),
        user=os.getenv("KB_DB_USER", "postgres"),
        password=os.getenv("KB_DB_PASSWORD"),
    )


def fetch_missing_chunks():
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT chunk_id, text_raw
                FROM chunks
                WHERE embedding IS NULL AND text_raw IS NOT NULL
                ORDER BY chunk_id;
                """
            )
            return cur.fetchall()
    finally:
        conn.close()


def embed_batch(texts: list[str]) -> list[list[float]]:
    response = client.embeddings.create(model=EMBEDDING_MODEL, input=texts)
    return [d.embedding for d in response.data]


def update_embeddings(rows):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            for chunk_id, embedding in rows:
                cur.execute(
                    "UPDATE chunks SET embedding = %s WHERE chunk_id = %s;",
                    (embedding, chunk_id),
                )
        conn.commit()
    finally:
        conn.close()


def main():
    if not os.getenv("OPENAI_API_KEY"):
        print("⚠️  OPENAI_API_KEY manquante dans .env.")
        return

    missing = fetch_missing_chunks()
    print(f"Found {len(missing)} chunks without an embedding.")

    if not missing:
        print("Nothing to do.")
        return

    for i in range(0, len(missing), BATCH_SIZE):
        batch = missing[i : i + BATCH_SIZE]
        texts = [row["text_raw"] for row in batch]
        chunk_ids = [row["chunk_id"] for row in batch]

        print(f"Embedding batch {i // BATCH_SIZE + 1} ({len(batch)} chunks) ...")
        embeddings = embed_batch(texts)
        update_embeddings(list(zip(chunk_ids, embeddings)))
        time.sleep(0.2)  # gentle on rate limits

    print(f"✅ Done. Embedded {len(missing)} chunks.")


if __name__ == "__main__":
    main()
