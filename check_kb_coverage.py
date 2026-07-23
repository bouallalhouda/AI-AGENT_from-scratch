"""
LegalPlus Knowledge Base — Coverage Diagnostic

Checks two things:
1. Which documents (doc_id) exist in the `chunks` table, and how many
   chunks each contains — to see the overall shape of the knowledge base.
2. Whether anything related to trademarks ("marque", "OMPIC", "propriete
   industrielle") exists at all, using plain keyword search (not vector),
   since keyword search is more reliable to answer "does this word exist
   anywhere in the base" than similarity search.

Usage:
    python check_kb_coverage.py
"""

import os
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv

load_dotenv()


def get_connection():
    return psycopg2.connect(
        host=os.getenv("KB_DB_HOST", "localhost"),
        port=os.getenv("KB_DB_PORT", "5432"),
        dbname=os.getenv("KB_DB_NAME", "legalplus"),
        user=os.getenv("KB_DB_USER", "postgres"),
        password=os.getenv("KB_DB_PASSWORD"),
    )


def list_documents():
    sql = """
        SELECT doc_id, COUNT(*) AS nb_chunks
        FROM chunks
        GROUP BY doc_id
        ORDER BY nb_chunks DESC;
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql)
            rows = cur.fetchall()
    finally:
        conn.close()
    return rows


def search_keyword_across_docs(keyword: str):
    sql = """
        SELECT doc_id, COUNT(*) AS nb_matches
        FROM chunks
        WHERE LOWER(text_raw) LIKE LOWER(%s)
        GROUP BY doc_id
        ORDER BY nb_matches DESC;
    """
    conn = get_connection()
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(sql, (f"%{keyword}%",))
            rows = cur.fetchall()
    finally:
        conn.close()
    return rows


def main():
    print("=" * 60)
    print("1. Documents présents dans la base (doc_id)")
    print("=" * 60)
    docs = list_documents()
    if not docs:
        print("Aucun document trouvé — la table `chunks` semble vide.")
    else:
        for d in docs:
            print(f"  {d['doc_id']:<60} {d['nb_chunks']} chunks")

    print("\n" + "=" * 60)
    print("2. Recherche de contenu lié aux marques")
    print("=" * 60)

    keywords = ["marque", "OMPIC", "propriété industrielle", "dépôt de marque"]
    for kw in keywords:
        print(f"\n--- Mot-clé : '{kw}' ---")
        results = search_keyword_across_docs(kw)
        if not results:
            print("  Aucune occurrence trouvée dans aucun document.")
        else:
            for r in results:
                print(f"  {r['doc_id']:<60} {r['nb_matches']} occurrence(s)")


if __name__ == "__main__":
    main()
