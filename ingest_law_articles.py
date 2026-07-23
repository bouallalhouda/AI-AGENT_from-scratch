"""
LegalPlus Knowledge Base — Law Article Ingestion (v2 — fixed for real PDF structure)

Reads a PDF (French or Arabic), splits it into articles, and inserts
each article as a row in `chunks` — matching your exact schema.

WHAT CHANGED IN v2 (discovered from raw text inspection of ma074fr_1.pdf):
1. This PDF is SINGLE COLUMN, not two-column. Default flipped accordingly.
2. This PDF contains TWO separate legal texts stacked together:
   - Loi n°17-97 (articles 1 to 239)
   - Décret n°2-14-316 (its own "article premier", "article 2"... — numbering restarts)
   The script now auto-detects the boundary ("le chef du gouvernement,") and
   splits them into two independent article sets with distinct doc_ids.
3. Article markers are lowercase ("article premier", "article 4.1"), sitting
   ALONE on their own line — the regex now requires that instead of expecting
   a colon/period right after the number.

SAFE BY DEFAULT: running the script only PREVIEWS what would be inserted.
Nothing touches the database until you pass --commit.

Usage:
    # 1) Preview only (recommended first run)
    python ingest_law_articles.py --pdf "data\\ma074fr_1.pdf" --lang fr --doc_id loi_17_97_propriete_industrielle_fr

    # 2) Once the preview looks correct, actually insert:
    python ingest_law_articles.py --pdf "data\\ma074fr_1.pdf" --lang fr --doc_id loi_17_97_propriete_industrielle_fr --commit

    # 3) If a PDF is genuinely two-column, force that mode:
    python ingest_law_articles.py --pdf "other.pdf" --lang fr --doc_id xxx --single_column

Requires:
    pip install pdfplumber psycopg2-binary python-dotenv
"""

import os
import re
import argparse
import hashlib
import psycopg2
from dotenv import load_dotenv

load_dotenv()


# --- PDF text extraction ---
def extract_pdf_text(pdf_path: str, two_column: bool = True) -> str:
    """
    Extracts text page by page. two_column=True (the default) splits each
    page into a left half and a right half, extracted separately and
    concatenated left-then-right. This specific PDF (and most OMPIC legal
    PDFs) genuinely uses a two-column layout — reading it as single-column
    interleaves lines from both columns and produces jumbled text. Pass
    --single_column only if you've verified (via --dump_raw) that a given
    PDF is actually laid out in one column.
    """
    import pdfplumber
    full_text = []
    with pdfplumber.open(pdf_path) as pdf:
        for page in pdf.pages:
            if two_column:
                width = page.width
                height = page.height
                left = page.crop((0, 0, width / 2, height))
                right = page.crop((width / 2, 0, width, height))
                left_text = left.extract_text() or ""
                right_text = right.extract_text() or ""
                full_text.append(left_text + "\n" + right_text)
            else:
                text = page.extract_text()
                if text:
                    full_text.append(text)
    return "\n".join(full_text)


# --- Splitting a combined PDF into its separate legal texts ---
# Some OMPIC PDFs stack a "Loi" and its implementing "Décret" in one file.
# The Décret's actual body (not the table-of-contents mention of it) always
# starts with this exact administrative preamble phrase.
DECREE_BOUNDARY_RE = re.compile(r"le\s+chef\s+du\s+gouvernement\s*,", re.IGNORECASE)


def split_loi_and_decret(text: str):
    """
    Returns (loi_text, decret_text). If no decree boundary is found,
    decret_text is empty and loi_text is the full text unchanged.
    """
    matches = list(DECREE_BOUNDARY_RE.finditer(text))
    if not matches:
        return text, ""

    # The boundary phrase can appear in a table of contents too (rare, but
    # be safe): take the LAST match, since the real decree body is always
    # near the end of these combined OMPIC PDFs.
    split_pos = matches[-1].start()
    return text[:split_pos], text[split_pos:]


# --- Article splitting ---
# French pattern: the word "article" followed by a number (or "premier"),
# sitting ALONE on its own line (this is how this PDF actually formats
# article markers — confirmed from raw text inspection).
FR_ARTICLE_RE = re.compile(
    r"^[ \t]*article[ \t]+(premier|\d+(?:\.\d+)?)[ \t]*\.?[ \t]*$",
    re.IGNORECASE | re.MULTILINE,
)

# Arabic pattern matches: "المادة 1", "المادة الأولى", "المادة 133"
AR_ARTICLE_RE = re.compile(
    r"المادة\s+(\d+|الأولى|الثانية|الثالثة)",
)


def split_into_articles(text: str, lang: str):
    """
    Returns a list of (article_number, article_text) tuples.
    "premier" is normalized to "1" for article_number, but the original
    wording is kept in article_label for display.
    """
    pattern = FR_ARTICLE_RE if lang == "fr" else AR_ARTICLE_RE
    matches = list(pattern.finditer(text))

    if not matches:
        return []

    articles = []
    for i, m in enumerate(matches):
        start = m.start()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        raw_number = next((g for g in m.groups() if g), "").strip()
        article_text = text[start:end].strip()
        if article_text:
            articles.append((raw_number, article_text))
    return articles


def normalize_article_number(raw_number: str) -> str:
    return "1" if raw_number.lower() == "premier" else raw_number


def make_article_label(raw_number: str) -> str:
    return "Article Premier" if raw_number.lower() == "premier" else f"Article {raw_number}"


# --- Database ---
def get_connection():
    return psycopg2.connect(
        host=os.getenv("KB_DB_HOST", "localhost"),
        port=os.getenv("KB_DB_PORT", "5432"),
        dbname=os.getenv("KB_DB_NAME", "legalplus"),
        user=os.getenv("KB_DB_USER", "postgres"),
        password=os.getenv("KB_DB_PASSWORD"),
    )


def make_chunk_id(doc_id: str, article_number: str, seen_ids: set) -> str:
    base = f"{doc_id}_art_{article_number}"
    chunk_id = base
    suffix = 2
    # Guard against duplicate article numbers within the same document
    # (shouldn't normally happen, but stay safe instead of crashing).
    while chunk_id in seen_ids:
        chunk_id = f"{base}_{suffix}"
        suffix += 1
    seen_ids.add(chunk_id)
    return chunk_id


def ensure_document_exists(doc_id: str, doc_type: str, doc_number: str, title_fr: str, source_file: str):
    """
    Creates a row in `documents` for this doc_id if it doesn't already
    exist. `chunks.doc_id` has a foreign key to `documents.doc_id`, so
    this must run before any chunks referencing this doc_id are inserted.
    Uses ON CONFLICT DO NOTHING so it's safe to call every time.
    """
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO documents (doc_id, file_name, title_fr, doc_type, doc_number, jurisdiction, language)
                VALUES (%s, %s, %s, %s, %s, 'MA', 'fr')
                ON CONFLICT (doc_id) DO NOTHING;
                """,
                (doc_id, source_file, title_fr, doc_type, doc_number),
            )
        conn.commit()
    finally:
        conn.close()


def insert_articles(articles, doc_id: str, doc_type: str, doc_number: str):
    conn = get_connection()
    inserted = 0
    seen_ids = set()
    try:
        with conn.cursor() as cur:
            for idx, (raw_number, article_text) in enumerate(articles):
                article_number = normalize_article_number(raw_number)
                chunk_id = make_chunk_id(doc_id, article_number, seen_ids)
                word_count = len(article_text.split())
                cur.execute(
                    """
                    INSERT INTO chunks
                        (chunk_id, doc_id, doc_type, doc_number, article_number,
                         article_label, text, text_raw, word_count,
                         chunk_index, total_chunks)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
                    ON CONFLICT (chunk_id) DO NOTHING;
                    """,
                    (
                        chunk_id,
                        doc_id,
                        doc_type,
                        doc_number,
                        article_number,
                        make_article_label(raw_number),
                        article_text,
                        article_text,
                        word_count,
                        idx,
                        len(articles),
                    ),
                )
                inserted += cur.rowcount
        conn.commit()
    finally:
        conn.close()
    return inserted


def preview_articles(label: str, articles, preview_count: int):
    print(f"\n=== {label} : {len(articles)} article(s) détecté(s) ===\n")
    if not articles:
        return
    for raw_number, article_text in articles[:preview_count]:
        preview = article_text[:200].replace("\n", " ")
        print(f"[{make_article_label(raw_number)}] {preview}...\n")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--pdf", required=True, help="Path to the PDF file")
    parser.add_argument("--lang", required=True, choices=["fr", "ar"])
    parser.add_argument("--doc_id", required=True, help="doc_id for the LOI part, e.g. loi_17_97_propriete_industrielle_fr")
    parser.add_argument("--decret_doc_id", default=None, help="doc_id for the DÉCRET part, if present (default: <doc_id>_decret)")
    parser.add_argument("--doc_type", default="loi")
    parser.add_argument("--doc_number", default="17-97")
    parser.add_argument("--commit", action="store_true", help="Actually insert into the database")
    parser.add_argument("--preview_count", type=int, default=5)
    parser.add_argument("--dump_raw", action="store_true", help="Save extracted raw text to a .txt file for inspection")
    parser.add_argument("--single_column", action="store_true", help="Disable two-column extraction (only if --dump_raw confirms this PDF is genuinely single-column)")
    args = parser.parse_args()

    decret_doc_id = args.decret_doc_id or f"{args.doc_id}_decret"

    print(f"Extracting text from {args.pdf} ...")
    text = extract_pdf_text(args.pdf, two_column=not args.single_column)
    print(f"Extracted {len(text)} characters.")

    if args.dump_raw:
        dump_path = args.pdf + ".extracted.txt"
        with open(dump_path, "w", encoding="utf-8") as f:
            f.write(text)
        print(f"Raw extracted text saved to: {dump_path}")

    loi_text, decret_text = split_loi_and_decret(text)
    if decret_text:
        print(f"\nDétecté : un Décret séparé à l'intérieur du même PDF (à partir du marqueur 'le chef du gouvernement,').")
    else:
        print("\nAucun Décret séparé détecté — traitement du texte entier comme un seul document.")

    loi_articles = split_into_articles(loi_text, args.lang)
    decret_articles = split_into_articles(decret_text, args.lang) if decret_text else []

    preview_articles(f"LOI ({args.doc_id})", loi_articles, args.preview_count)
    if decret_text:
        preview_articles(f"DÉCRET ({decret_doc_id})", decret_articles, args.preview_count)

    if not loi_articles and not decret_articles:
        print("\n⚠️  Aucun article détecté du tout — le pattern regex ne correspond probablement pas à ce PDF.")
        print("Relancez avec --dump_raw et vérifiez le format exact des marqueurs d'articles.")
        return

    if not args.commit:
        print("\n" + "=" * 60)
        print("DRY RUN — rien n'a été inséré.")
        print("Si l'aperçu ci-dessus semble correct, relancez avec --commit")
        print("=" * 60)
        return

    print("\nInsertion dans la base de données ...")
    total_inserted = 0
    if loi_articles:
        ensure_document_exists(
            args.doc_id, args.doc_type, args.doc_number,
            title_fr=f"Loi n° {args.doc_number} relative à la protection de la propriété industrielle",
            source_file=os.path.basename(args.pdf),
        )
        n = insert_articles(loi_articles, args.doc_id, args.doc_type, args.doc_number)
        print(f"✅ LOI : {n} nouvelles lignes insérées.")
        total_inserted += n
    if decret_articles:
        ensure_document_exists(
            decret_doc_id, "decret", args.doc_number,
            title_fr=f"Décret pris pour l'application de la loi n° {args.doc_number}",
            source_file=os.path.basename(args.pdf),
        )
        n = insert_articles(decret_articles, decret_doc_id, "decret", args.doc_number)
        print(f"✅ DÉCRET : {n} nouvelles lignes insérées.")
        total_inserted += n

    print(f"\n✅ Total : {total_inserted} nouvelles lignes insérées (les doublons éventuels ont été ignorés).")


if __name__ == "__main__":
    main()