import os
import sys
import json
import re
from dotenv import load_dotenv
from groq import Groq

# --- Setup ---
load_dotenv()
client = Groq(api_key=os.getenv("GROQ_API_KEY"))

# --- Load the field config ---
# --- Load the field config (workflow file passed as argument, e.g. python main.py fields_trademark.json) ---
config_filename = sys.argv[1] if len(sys.argv) > 1 else "fields_sarl.json"
print(f"(Workflow charge : {config_filename})")

with open(config_filename, "r", encoding="utf-8") as f:
    config = json.load(f)

core_fields = config["core_fields"]
optional_addons = config["optional_addons"]

collected_data = {}


def call_llm(prompt):
    response = client.chat.completions.create(
        model="llama-3.3-70b-versatile",
        messages=[{"role": "user", "content": prompt}],
    )
    return response.choices[0].message.content.strip()



def detect_and_answer_question(question_asked, user_answer):
    """
    Checks if the user is asking a question instead of answering.
    If so, prints a helpful answer and returns True.
    Otherwise returns False (caller should proceed with normal extraction).
    """
    is_question_prompt = f"""You classify a user's message as either ANSWER or QUESTION. Follow the examples exactly.

The user was asked: "{question_asked}"

RULES:
- ANSWER = the message contains a usable answer (a name, a number, a choice), even if incomplete or also includes some extra talk.
- QUESTION = the message is ONLY asking for help/explanation/suggestions, with no usable answer at all.
- If the message contains BOTH a real answer AND a question, classify it as ANSWER (the answer part will be extracted separately).

EXAMPLES:

Message: "je sais pas, aide moi a choisir"
Output: QUESTION

Message: "c'est quoi la domiciliation?"
Output: QUESTION

Message: "propose moi des noms"
Output: QUESTION

Message: "houda"
Output: ANSWER

Message: "je veux les noms : houda, hudauy, pharmait"
Output: ANSWER

Message: "mon entreprise est liee a l'IT, propose moi des noms avec mon nom Houda"
Output: QUESTION

Now classify this message. Reply with ONLY one word: "ANSWER" or "QUESTION".

Message: "{user_answer}"
Output:"""
    intent = call_llm(is_question_prompt).strip().upper()

    if "QUESTION" in intent:
        help_prompt = f"""The user was asked: "{question_asked}"
Instead of giving a usable answer, they asked: "{user_answer}"

Respond helpfully in French, in 1-3 short sentences, explaining what they
asked about in the context of a Moroccan company creation service (LegalPlus).
Do not invent company names unless they explicitly describe their business activity."""
        helpful_reply = call_llm(help_prompt)
        print(f"\nAI: {helpful_reply}")
        return True

    return False


def normalize_yes_no(text):
    """
    Uses the LLM to normalize a free-text answer into True/False/None.
    """
    prompt = f"""
The user answered: "{text}"

Does this mean YES or NO (in the context of wanting/accepting something)?
Reply with ONLY one word: "YES", "NO", or "UNCLEAR" if you truly cannot tell.
"""
    result = call_llm(prompt).strip().upper()
    if result == "YES":
        return True
    elif result == "NO":
        return False
    else:
        return None


def ask_llm_to_extract(field_name, question, conversation_history):
    """
    Ask the user a question, then use the LLM to extract a clean value
    from their free-text answer.
    """
    print(f"\nAI: {question}")
    user_answer = input("You: ")

    conversation_history.append({"role": "assistant", "content": question})
    conversation_history.append({"role": "user", "content": user_answer})

    # --- Special case: signature_type must be one of two fixed choices ---
    if field_name == "signature_type":
        if detect_and_answer_question(question, user_answer):
            return "UNCLEAR", conversation_history, True

        extraction_prompt = f"""
The user was asked whether the signature type is "séparée" (separate) or "conjointe" (joint).
They answered: "{user_answer}"

Reply with ONLY one word: "SEPAREE", "CONJOINTE", or "UNCLEAR" if you cannot tell.
"""
        result = call_llm(extraction_prompt).strip().upper()
        if result == "SEPAREE":
            return "separate", conversation_history, False
        elif result == "CONJOINTE":
            return "joint", conversation_history, False
        else:
            return "UNCLEAR", conversation_history, False

    # --- Special case: detect if the user is asking a question instead of answering ---
    # (company_name_choices handles its own question detection below, with real suggestions)
    if field_name != "company_name_choices":
        if detect_and_answer_question(question, user_answer):
            return "UNCLEAR", conversation_history, True

    if field_name == "company_name_choices":
        # First, check if the user mentioned their business activity in this message —
        # remember it so we can generate relevant suggestions even across multiple turns.
        activity_check_prompt = f"""The user is choosing a company name and said: "{user_answer}"

Do they mention what their business activity/sector is (e.g. transport, IT, pharmacy)?
If yes, reply with ONLY the activity in French, a few words max (e.g. "transport de marchandises").
If no activity is mentioned, reply with ONLY: NONE
"""
        activity_hint = call_llm(activity_check_prompt).strip()
        if activity_hint.upper() != "NONE" and len(activity_hint) < 60:
            collected_data["_activity_hint"] = activity_hint

        # Check if this message is a request for help/suggestions rather than actual names
        is_question_prompt = f"""The user was asked to propose company names. Classify their message.

RULES:
- ANSWER = they clearly state one or more final, ready-to-use names (proper nouns, brand-like).
- QUESTION = they are asking for suggestions, ideas, or want the AI to generate/combine names for them
  — even if they mention a word, theme, or their own name as INSPIRATION rather than a final answer.

EXAMPLES:

Message: "Atlas Tech"
Output: ANSWER

Message: "combine mon nom Houda et data"
Output: QUESTION

Message: "quelque chose avec mon nom Houda et IT"
Output: QUESTION

Message: "je veux un nom avec Houda dedans, propose"
Output: QUESTION

Message: "HoudaTech"
Output: ANSWER

Message: "aide moi a choisir"
Output: QUESTION

Now classify this message. Reply with ONLY one word: "ANSWER" or "QUESTION".

Message: "{user_answer}"
Output:"""
        intent = call_llm(is_question_prompt).strip().upper()

        if "QUESTION" in intent:
            known_activity = collected_data.get("_activity_hint")
            existing_so_far = collected_data.get("company_name_choices", []) or []

            suggestion_prompt = f"""Generate exactly 3 short, creative, realistic company name
suggestions for a Moroccan business{f" in the sector: {known_activity}" if known_activity else ""}.
The user gave this specific request/preference, follow it closely if relevant: "{user_answer}"
{"Avoid repeating these already-chosen names: " + ", ".join(existing_so_far) if existing_so_far else ""}
Return ONLY the 3 names separated by commas, nothing else. No numbering, no explanation."""
            suggestions = call_llm(suggestion_prompt)
            print(f"\nAI: Voici 3 suggestions : {suggestions}. Dites-moi lesquelles vous convainquent, ou proposez vos propres noms.")
            return "UNCLEAR", conversation_history, True

        extraction_prompt = f"""You extract company names from a user's message. Follow the examples exactly.

RULES:
- Only extract things that are CLEARLY proposed as a company/business name.
- Ignore filler words, questions, requests for help, or unrelated text.
- A name is usually 1-3 words, capitalized like a brand name.
- If the user is asking a question or asking for suggestions, extract NOTHING (empty array).

EXAMPLES:

Message: "houda"
Output: ["Houda"]

Message: "je propose Atlas Tech et Nova Solutions"
Output: ["Atlas Tech", "Nova Solutions"]

Message: "je sais pas, aide moi a choisir"
Output: []

Message: "propose moi des noms stp"
Output: []

Message: "les noms : houda, hudauy, pharmait"
Output: ["Houda", "Hudauy", "Pharmait"]

Message: "mon entreprise est liee a l'IT, propose moi des noms"
Output: []

Now extract from this message. Reply with ONLY the JSON array, nothing else, no explanation:

Message: "{user_answer}"
Output:"""
        raw = call_llm(extraction_prompt)
        try:
            # Defensive: strip any accidental markdown code fences
            cleaned_raw = raw.strip().strip("`").replace("json", "", 1).strip() if raw.strip().startswith("```") else raw.strip()
            new_names = json.loads(cleaned_raw)
            if not isinstance(new_names, list):
                new_names = []
        except (json.JSONDecodeError, ValueError):
            new_names = []

        # Merge with names already collected so far (avoid duplicates, case-insensitive)
        existing = collected_data.get("company_name_choices", []) or []
        existing_lower = [n.lower() for n in existing]
        for n in new_names:
            if n.lower() not in existing_lower:
                existing.append(n)
                existing_lower.append(n.lower())

        collected_data["company_name_choices"] = existing

        if len(existing) >= 3:
            return existing[:3], conversation_history, False
        else:
            missing = 3 - len(existing)
            print(f"   (Noms reçus jusqu'à présent: {existing if existing else 'aucun'} — il en manque {missing})")
            return "UNCLEAR", conversation_history, False

    # --- Special case: phone number needs validation, not just extraction ---
    if field_name == "associate_phone":
        validated = validate_moroccan_phone(user_answer)
        if validated:
            return validated, conversation_history, False
        else:
            return "UNCLEAR", conversation_history, False

    # --- Special case: detect "it's me" answers as a structured flag, not free text ---
    if field_name in ("associate_name", "manager_name"):
        self_reference_prompt = f"""The user was asked: "{question}"
They answered: "{user_answer}"

Are they saying THEY THEMSELVES will hold this role (e.g. "moi", "c'est moi",
"MOI", "je serai le gerant"), rather than naming someone else?

Reply with ONLY one word: "SELF" or "OTHER".
"""
        ref = call_llm(self_reference_prompt).strip().upper()
        if "SELF" in ref:
            return "__SELF__", conversation_history, False
        # otherwise fall through to generic extraction below for a real name

    # --- Default case: generic extraction ---
    extraction_prompt = f"""You extract a clean value from a user's answer. Follow the examples exactly.

Question asked: "{question}"

RULES:
- Return ONLY the extracted value, nothing else. No explanation, no quotes, no extra words.
- Expand short/informal answers into clean, professional values (e.g. "ai" -> "Intelligence Artificielle").
- If the answer is truly empty, off-topic, or you cannot extract a value, return exactly: UNCLEAR

EXAMPLES:

Question: "Quelle est l'activite de votre societe ?"
Answer: "IA"
Output: Intelligence Artificielle

Question: "Quelle est l'activite de votre societe ?"
Answer: "transport"
Output: Transport

Question: "Quel est le nom du premier associe ?"
Answer: "je sais pas"
Output: UNCLEAR

Now extract from this answer. Reply with ONLY the value or UNCLEAR:

Answer: "{user_answer}"
Output:"""
    extracted_value = call_llm(extraction_prompt)
    return extracted_value, conversation_history, False


def run_conversation():
    print("=" * 50)
    print("👋 Bienvenue chez LegalPlus AI")
    print("Je vais vous aider à créer votre société (SARL).")
    print("=" * 50)

    conversation_history = []

    # --- Phase 1: Core fields (mandatory) ---
    print("\n--- Informations obligatoires ---")
    for field in core_fields:
        name = field["name"]
        question = field["question"]

        value, conversation_history, was_question = ask_llm_to_extract(
            name, question, conversation_history
        )

        retries = 0
        total_attempts = 0
        max_retries = 6 if name == "company_name_choices" else 3
        max_total = 10 if name == "company_name_choices" else 8
        while value == "UNCLEAR" and retries < max_retries and total_attempts < max_total:
            if not was_question:
                if name == "company_name_choices":
                    have = collected_data.get("company_name_choices", []) or []
                    missing = 3 - len(have)
                    print(f"AI: Il me faut encore {missing} nom(s) distinct(s). Exemple: 'Atlas Tech, Nova Solutions'.")
                elif name == "associate_phone":
                    print("AI: Ce numéro ne semble pas valide. Format attendu: 06XXXXXXXX ou +212XXXXXXXXX.")
                elif name != "signature_type":
                    print("AI: Je n'ai pas bien compris, pouvez-vous reformuler ?")

            # Track progress specifically for company_name_choices (accumulator field)
            names_before = len(collected_data.get("company_name_choices", []) or []) if name == "company_name_choices" else None

            value, conversation_history, was_question = ask_llm_to_extract(
                name, question, conversation_history
            )

            total_attempts += 1

            if was_question:
                continue  # questions never count against retries

            if name == "company_name_choices":
                names_after = len(collected_data.get("company_name_choices", []) or [])
                if names_after > names_before:
                    # Progress was made — don't count this as a failed retry
                    continue

            retries += 1

        if value == "UNCLEAR":
            print("AI: On continue, vous pourrez corriger ce champ plus tard avec votre conseiller.")
            value = None

        if value == "__SELF__":
            collected_data[name] = None
            collected_data[f"{name}_is_declarant"] = True
            print(f"   ✅ Enregistré: {name}_is_declarant = True")
        else:
            collected_data[name] = value
            print(f"   ✅ Enregistré: {name} = {value}")

    # --- Phase 2: Optional add-ons (normalized to booleans) ---
    print("\n--- Services additionnels (optionnels) ---")
    for addon in optional_addons:
        name = addon["name"]
        question = addon["question"]

        print(f"\nAI: {question} (tapez 'skip' pour ignorer)")
        user_answer = input("You: ")

        attempts = 0
        while detect_and_answer_question(question, user_answer) and attempts < 3:
            print(f"\nAI: {question} (tapez 'skip' pour ignorer)")
            user_answer = input("You: ")
            attempts += 1

        if user_answer.strip().lower() == "skip":
            print(f"   ⏭️  Ignoré: {name} (non renseigné)")
        else:
            normalized = normalize_yes_no(user_answer)
            if normalized is not None:
                collected_data[name] = normalized
                print(f"   ✅ Enregistré: {name} = {normalized}")
            else:
                print(f"   ⏭️  Réponse ambiguë, {name} laissé non renseigné")

    # --- Final summary ---
    print("\n" + "=" * 50)
    # Remove internal helper fields that aren't part of the actual business data
    collected_data.pop("_activity_hint", None)

    # Attach metadata BEFORE printing, so the console summary matches the saved file
    import datetime

    draft_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
    collected_data["draft_id"] = draft_id
    collected_data["workflow"] = config_filename.replace("fields_", "").replace(".json", "")
    collected_data["created_at"] = datetime.datetime.now().isoformat()

    print("📋 Résumé de votre demande :")
    print(json.dumps(collected_data, indent=2, ensure_ascii=False))
    print("=" * 50)

    # Save to a local file WITHOUT erasing previous sessions
    # (simulating "sending to backend" — each session becomes its own draft record)

    # Load existing drafts if the file already exists, otherwise start a new list
    all_drafts = []
    if os.path.exists("draft_output.json"):
        try:
            with open("draft_output.json", "r", encoding="utf-8") as f:
                existing_content = json.load(f)
                if isinstance(existing_content, list):
                    all_drafts = existing_content
                else:
                    # Old format (single dict) — migrate it into a list
                    all_drafts = [existing_content]
        except (json.JSONDecodeError, ValueError):
            all_drafts = []

    all_drafts.append(collected_data)

    with open("draft_output.json", "w", encoding="utf-8") as f:
        json.dump(all_drafts, f, indent=2, ensure_ascii=False)

    print(f"\n✅ Votre demande a été enregistrée (draft_id: {draft_id}).")
    print(f"Total de demandes enregistrées jusqu'à présent: {len(all_drafts)}")
    print("Un conseiller LegalPlus vous contactera bientôt.")


if __name__ == "__main__":
    run_conversation()