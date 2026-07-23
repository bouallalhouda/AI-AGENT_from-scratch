"""
LegalPlus Knowledge Base — Vector Search (Step 2 of RAG pipeline)

Uses OpenAI's text-embedding-3-small to vectorize the user's question,
then compares it against the EXISTING `embedding` column in `chunks`
(already generated with the same OpenAI model) using cosine similarity
via pgvector.

This replaces the keyword LIKE search in search_kb.py with real
semantic search — it should understand that "gérant" relates to
"administrateur" or "gestion de société" even without an exact match.

Usage:
    python search_kb_vector.py

Requires in .env:
    OPENAI_API_KEY=sk-...
    KB_DB_HOST, KB_DB_PORT, KB_DB_NAME, KB_DB_USER, KB_DB_PASSWORD
"""

import os
import unicodedata
from typing import Optional
import psycopg2
import psycopg2.extras
from pydantic import BaseModel
from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

EMBEDDING_MODEL = "text-embedding-3-small"

# En dessous de ce score, on considère qu'un résultat n'est pas assez fiable
# pour être affiché comme pertinent (voir tests "sosciete" / "opposition" :
# le bruit apparaît généralement sous ~0.45).
SIMILARITY_THRESHOLD = 0.45

client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))


# --- Data model ---
class ChunkResult(BaseModel):
    chunk_id: str
    doc_id: Optional[str] = None
    article_number: Optional[str] = None
    article_label: Optional[str] = None
    text_raw: str
    word_count: Optional[int] = None
    similarity: Optional[float] = None


# --- Database connection ---
def get_connection():
    return psycopg2.connect(
        host=os.getenv("KB_DB_HOST", "localhost"),
        port=os.getenv("KB_DB_PORT", "5432"),
        dbname=os.getenv("KB_DB_NAME", "legalplus"),
        user=os.getenv("KB_DB_USER", "postgres"),
        password=os.getenv("KB_DB_PASSWORD"),
    )


def normalize_text(text: str) -> str:
    """Minuscule + suppression des accents (é->e, ô->o, etc.)."""
    text = text.lower().strip()
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(c for c in decomposed if not unicodedata.combining(c))


# Prix officiel OpenAI pour text-embedding-3-small (au 2026) — à ajuster si le tarif change.
PRICE_PER_1M_TOKENS = 0.02

# Compteur cumulé sur la session (remis à zéro à chaque lancement du script).
session_tokens_used = 0


# --- Embed the user's question with the SAME model used for the chunks ---
def embed_query(text: str) -> tuple[list[float], int]:
    response = client.embeddings.create(
        model=EMBEDDING_MODEL,
        input=text,
    )
    tokens_used = response.usage.total_tokens
    return response.data[0].embedding, tokens_used


# --- Vector similarity search (cosine distance via pgvector) ---
def search_chunks_vector(query: str, limit: int = 5) -> list[ChunkResult]:
    global session_tokens_used
    query_embedding, tokens_used = embed_query(query)
    session_tokens_used += tokens_used

    # pgvector's <=> operator returns COSINE DISTANCE (0 = identical, 2 = opposite).
    # We convert to a similarity score (1 = identical, 0 = unrelated) for readability.
    sql = """
        SELECT
            chunk_id, doc_id, article_number, article_label, text_raw, word_count,
            1 - (embedding <=> %s::vector) AS similarity
        FROM chunks
        WHERE embedding IS NOT NULL
        ORDER BY embedding <=> %s::vector
        LIMIT %s;
    """

    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (query_embedding, query_embedding, limit))
            rows = cur.fetchall()
    finally:
        conn.close()

    return [ChunkResult(**row) for row in rows]


# --- Retry with a normalized (accent-stripped) query only if the raw
# query scored poorly — avoids degrading well-typed accented queries. ---
FALLBACK_RETRY_BELOW = 0.55


def search_with_fallback(query: str, limit: int = 5) -> tuple[list[ChunkResult], bool]:
    results = search_chunks_vector(query, limit=limit)
    used_fallback = False

    top_score = results[0].similarity if results else 0
    normalized = normalize_text(query)

    if top_score is not None and top_score < FALLBACK_RETRY_BELOW and normalized != query.lower().strip():
        fallback_results = search_chunks_vector(normalized, limit=limit)
        fallback_top = fallback_results[0].similarity if fallback_results else 0
        if fallback_top is not None and top_score is not None and fallback_top > top_score:
            results = fallback_results
            used_fallback = True

    return results, used_fallback


def print_results(results: list[ChunkResult], used_fallback: bool = False) -> None:
    if not results:
        print("Aucun résultat trouvé pour cette recherche.")
        return

    if used_fallback:
        print("\n(ℹ️  Score faible sur la requête originale — nouvel essai avec une version sans accents/majuscules, meilleurs résultats obtenus)")

    kept = [r for r in results if (r.similarity or 0) >= SIMILARITY_THRESHOLD]
    dropped = len(results) - len(kept)

    if not kept:
        print(
            f"\nAucun résultat suffisamment pertinent trouvé "
            f"(le meilleur score était {results[0].similarity:.3f}, "
            f"sous le seuil de {SIMILARITY_THRESHOLD}).\n"
            f"Essayez de reformuler la question avec plus de contexte "
            f"(ex: préciser 'marque', 'société', 'travail'...)."
        )
        return

    print(f"\n{len(kept)} résultat(s) pertinent(s) trouvé(s) (recherche vectorielle) :\n")
    for i, chunk in enumerate(kept, start=1):
        print(f"--- Résultat {i} (similarité : {chunk.similarity:.3f}) ---")
        print(f"Article : {chunk.article_label or chunk.article_number or 'N/A'}")
        print(f"Doc ID  : {chunk.doc_id or 'N/A'}")
        print(f"Texte   : {chunk.text_raw[:400]}{'...' if len(chunk.text_raw) > 400 else ''}")
        print()

    if dropped:
        print(f"({dropped} résultat(s) supplémentaire(s) écarté(s) car sous le seuil de similarité)\n")


def main():
    print("=" * 60)
    print("Recherche dans la base de connaissances LegalPlus (vectorielle)")
    print("=" * 60)

    if not os.getenv("OPENAI_API_KEY"):
        print("\n⚠️  OPENAI_API_KEY manquante dans .env — ajoutez-la avant de continuer.")
        return

    while True:
        query = input("\nVotre question (ou 'quit' pour sortir) : ").strip()
        if query.lower() in ("quit", "exit", "q"):
            break
        if not query:
            continue

        try:
            tokens_before = session_tokens_used
            results, used_fallback = search_with_fallback(query, limit=5)
            print_results(results, used_fallback)

            tokens_this_query = session_tokens_used - tokens_before
            session_cost = (session_tokens_used / 1_000_000) * PRICE_PER_1M_TOKENS
            print(
                f"💬 Tokens pour cette requête : {tokens_this_query} "
                f"| Cumul session : {session_tokens_used} tokens "
                f"(≈ {session_cost:.6f} $)"
            )
        except Exception as e:
            print(f"Erreur lors de la recherche : {e}")


if __name__ == "__main__":
    main()