import json
import os
import re
import sys
from dotenv import load_dotenv
from openai import OpenAI
from tools import (
    validate_moroccan_phone,
    validate_email,
    update_field,
    set_signature_type,
    add_company_names,
    signature_type_applicable,
)
from tool_schemas import tools
from conversation_store import start_conversation, save_message

load_dotenv()
client = OpenAI(api_key=os.getenv("OPENAI_API_KEY"))

SELF_REFERENCE_VALUES = {
    "moi", "moi-même", "moi-meme", "moi meme", "c'est moi", "cest moi",
    "lui-même", "lui-meme", "lui meme", "myself", "me", "i am", "it's me",
}
NAME_FIELDS = {"associate_name", "manager_name"}


def _digits_only(s):
    return re.sub(r"\D", "", s or "")


def missing_required_fields(core_fields, collected_data):
    """Single source of truth for what's genuinely still missing."""
    missing = []
    for field in core_fields:
        name = field["name"]

        if name == "company_name_choices":
            names = collected_data.get(name, [])
            if not (isinstance(names, list) and len(names) >= 3):
                missing.append(name)

        elif name == "signature_type":
            if signature_type_applicable(collected_data) and not collected_data.get(name):
                missing.append(name)

        elif not collected_data.get(name):
            missing.append(name)

    return missing


def get_workflow_status(core_fields, collected_data, optional_addons=None):
    """
    Returns a short text summary of which fields are done vs still missing,
    so the LLM knows exactly where things stand.
    """
    done = []
    missing = []

    for field in core_fields:
        name = field["name"]
        question = field["question"]

        if name == "company_name_choices":
            names = collected_data.get(name, [])
            if isinstance(names, list) and len(names) >= 3:
                done.append(f"- {name}: {names}")
            else:
                count = len(names) if isinstance(names, list) else 0
                missing.append(f"- {name}: {question} (still need {3 - count} more name(s), have: {names if names else 'none'})")

        elif name == "signature_type":
            if not signature_type_applicable(collected_data):
                continue
            if collected_data.get(name):
                done.append(f"- {name}: {collected_data[name]}")
            else:
                missing.append(f"- {name}: {question}")

        elif collected_data.get(name):
            done.append(f"- {name}: {collected_data[name]}")
        else:
            missing.append(f"- {name}: {question}")

    addons_done = []
    addons_pending = []

    if optional_addons:
        for addon in optional_addons:
            name = addon["name"]
            question = addon["question"]
            if collected_data.get(name):
                addons_done.append(f"- {name}: {collected_data[name]}")
            else:
                addons_pending.append(f"- {name}: {question}")

    status = ""
    status += ("DONE (required):\n" + "\n".join(done) + "\n\n") if done else "DONE (required): (nothing yet)\n\n"
    status += ("STILL MISSING (required):\n" + "\n".join(missing) + "\n\n") if missing else "STILL MISSING (required): (nothing, all required fields complete)\n\n"
    if addons_done:
        status += "OPTIONAL - ANSWERED:\n" + "\n".join(addons_done) + "\n\n"
    if addons_pending:
        status += "OPTIONAL - NOT YET ASKED (user may decline any of these anytime):\n" + "\n".join(addons_pending) + "\n\n"

    return status


# A few concrete examples of the desired behavior, injected into every
# conversation. Few-shot examples are a more reliable lever for tool-calling
# consistency than another paragraph of "NEVER do X" — the model imitates
# the pattern shown instead of trying to satisfy a pile of negative rules.
FEW_SHOT_EXAMPLES = [
    {"role": "user", "content": "capital pro and prime"},
    {"role": "assistant", "content": None, "tool_calls": [{
        "id": "example1", "type": "function",
        "function": {"name": "add_company_names", "arguments": '{"names": ["capital pro", "prime"]}'}
    }]},
    {"role": "tool", "tool_call_id": "example1", "content": "{'count': 2, 'complete': False, 'names_so_far': ['capital pro', 'prime']}"},
    {"role": "assistant", "content": "Merci ! Il me faut encore un nom pour compléter les trois."},

    {"role": "user", "content": "0612345678"},
    {"role": "assistant", "content": None, "tool_calls": [{
        "id": "example2", "type": "function",
        "function": {"name": "validate_moroccan_phone", "arguments": '{"phone_number": "0612345678"}'}
    }]},
    {"role": "tool", "tool_call_id": "example2", "content": "0612345678"},
    {"role": "assistant", "content": "Merci, votre numéro est enregistré. Qui sera le gérant de la société ?"},
]


def build_system_prompt(status):
    return f"""ROLE
You are a friendly assistant at LegalPlus, a Moroccan legal-tech platform, guiding users through creating their SARL company via natural conversation instead of a rigid form.

STATUS (what's saved vs still needed)
{status}

SPECIAL RULES
- signature_type only applies if manager_name and associate_name are different people — if it's not listed above, don't ask about it.
- Exactly 3 distinct company names are required.
- Never invent or guess a phone number — only use digits the user actually typed.
- Filler words/acknowledgments ("oki", "ok", "d'accord", "oui", "non", "cool"...) are NOT company names, activities, or people's names — don't save them as such. Only save them as-is for addon questions (domiciliation, comptabilite) where "oui"/"non" IS a real answer.

TOOLS
- validate_moroccan_phone(phone_number) — the user gave a phone number.
- update_field(field_name, new_value) — activity, associate_name, manager_name, or an addon (domiciliation, comptabilite). Not for phone/names/signature.
- set_signature_type(value) — "separate" or "joint".
- add_company_names(names) — one or more proposed company names, called again each time more are given.

HOW TO BEHAVE
- The moment the user gives a usable value, call the matching tool immediately in that same turn — see the examples above. Don't announce it, don't ask for confirmation first, just call it and then reply based on the result.
- Ask about ONE missing field at a time, and always the FIRST one listed under "STILL MISSING (required)" in STATUS above — never skip ahead to a later field while an earlier one is still missing, even if the user's message seems to invite a different topic.
- If the user refuses a required field, briefly explain it's needed and ask again — don't drop it. Only optional addons can genuinely be skipped with "non".
- If the user says "moi"/"c'est moi" for a name, ask for their real nom et prénom instead — don't save "moi".
- If the user expresses uncertainty ("je ne sais pas", "je sais pas", "aucune idée", "i don't know") for a required field, don't just repeat the same question — briefly reassure them and offer 2-3 concrete examples relevant to that field to help them decide, then ask again.
- Only claim something is saved if STATUS above actually shows it under DONE.
- Only declare the workflow finished if STATUS shows no STILL MISSING fields and all addons answered.
- Respond in the same language the user used, defaulting to French.
- Keep replies short and natural — no raw data or field names shown to the user."""


FILLER_WORDS = {
    "oki", "ok", "okay", "d'accord", "daccord", "oui", "non", "yes", "no",
    "sure", "peut-etre", "peut être", "hmm", "euh", "bon", "voila", "voilà",
    "merci", "cool", "ouais", "yep", "nope",
}


def _is_plausible_name(value, max_words=6):
    """
    Sanity check applied AFTER the model has already decided to call a
    tool — never blocks the decision to call, only rejects an obviously
    wrong value (filler word, a whole sentence, a question) before it's
    saved. Used for company names and person names, which should always
    be short.
    """
    v = value.strip()
    if not v or "?" in v:
        return False
    if v.lower() in FILLER_WORDS:
        return False
    if len(v.split()) > max_words:
        return False
    return True


def _is_plausible_activity(value, max_words=12):
    v = value.strip()
    if not v or "?" in v:
        return False
    if len(v.split()) > max_words:
        return False
    return True


def execute_tool_calls(tool_calls, core_fields, optional_addons, collected_data, user_message):
    """
    The model chooses which tool to call and when — full flexibility.
    These checks only validate WHAT it sends, they never block it from
    calling a tool it's entitled to call.
    """
    addon_names = {a["name"] for a in (optional_addons or [])}
    user_digits = _digits_only(user_message)
    tool_responses = []

    for tool_call in tool_calls:
        args = json.loads(tool_call.function.arguments)
        result = None

        if tool_call.function.name == "validate_moroccan_phone":
            claimed = args.get("phone_number", "")
            claimed_digits = _digits_only(claimed)
            if not claimed_digits or claimed_digits not in user_digits:
                result = "rejected: this phone number does not appear anywhere in the user's actual message — never fabricate one, ask the user to (re)provide it"
            else:
                validated = validate_moroccan_phone(claimed)
                if validated:
                    collected_data["associate_phone"] = validated
                    result = validated
                else:
                    result = "rejected: invalid Moroccan phone number format"

        elif tool_call.function.name == "update_field":
            field_name = args.get("field_name")
            new_value = args.get("new_value", "")

            if field_name in NAME_FIELDS and new_value.strip().lower() in SELF_REFERENCE_VALUES:
                result = "rejected: cannot save a self-reference ('moi') as a name — ask for their real nom et prénom"
            elif field_name in NAME_FIELDS and not _is_plausible_name(new_value):
                result = "rejected: this doesn't look like a real name (too long, a question, or a filler word) — ask the user again for their actual nom et prénom"
            elif field_name == "activity" and not _is_plausible_activity(new_value):
                result = "rejected: this doesn't look like a real activity description — ask the user again"
            elif field_name in addon_names:
                still_missing = missing_required_fields(core_fields, collected_data)
                if still_missing:
                    result = f"rejected: required fields still missing ({', '.join(still_missing)}) — collect those before addons"
                else:
                    all_known_fields = core_fields + (optional_addons or [])
                    success = update_field(field_name, new_value, all_known_fields, collected_data)
                    result = "updated" if success else "rejected: unknown field name"
            else:
                all_known_fields = core_fields + (optional_addons or [])
                success = update_field(field_name, new_value, all_known_fields, collected_data)
                result = "updated" if success else "rejected: this field cannot be set via update_field (use its dedicated tool) or it's unknown"

        elif tool_call.function.name == "set_signature_type":
            success = set_signature_type(args["value"], collected_data)
            result = "updated" if success else "rejected: invalid value"

        elif tool_call.function.name == "add_company_names":
            candidates = args.get("names", [])
            plausible = [n for n in candidates if _is_plausible_name(n)]
            rejected = [n for n in candidates if n not in plausible]
            if plausible:
                result = add_company_names(plausible, collected_data)
                if rejected:
                    result["rejected_as_implausible"] = rejected
            else:
                result = "rejected: none of the proposed name(s) look like real company names (filler words, a question, or too long)"

        tool_responses.append({"role": "tool", "tool_call_id": tool_call.id, "content": str(result)})

    return tool_responses


def check_reply_matches_saved_data(user_message, reply, collected_data):
    """Catches the reply narrating/claiming a save that didn't actually happen this turn."""
    audit_prompt = f"""You are checking for ONE specific failure: the reply claims or implies that a \
SPECIFIC value has already been recorded/saved, when that exact value is NOT present in the ground \
truth data below.

This IS a mismatch, e.g.:
- Reply: "Merci, votre nom Karim Idrissi est enregistré." / Ground truth has no manager_name.
- Reply: "Votre société 'TechMaroc' est bien notée comme un des 3 noms." / Ground truth's company_name_choices doesn't contain "TechMaroc".

This is NOT a mismatch, e.g.:
- Reply: "Pas de souci, je suis là pour vous aider ! Pouvez-vous me donner le nom du gérant ?" \
(no specific value is claimed as saved — this is just a question/offer to help. OK even if ground \
truth is empty.)
- Reply: "Merci !" followed by the next question, with no specific value named. (OK)
- Reply restates what's still missing, or gives examples to help the user answer. (OK)

Only flag MISMATCH if the reply names a concrete value (a name, number, or specific text) as already \
saved/recorded/noted, and that value is genuinely absent from ground truth. A reply that merely asks \
a question, reassures, or offers examples is always OK, regardless of what's missing.

User's message: "{user_message}"
Assistant's reply: "{reply}"
Data actually saved (ground truth): {json.dumps(collected_data, ensure_ascii=False)}

Respond with ONLY one word: "MISMATCH" or "OK"."""
    audit = client.chat.completions.create(model="gpt-4o-mini", messages=[{"role": "user", "content": audit_prompt}])
    return "MISMATCH" in (audit.choices[0].message.content or "").strip().upper()


FALSE_COMPLETION_SIGNALS = [
    "récapitulatif final", "recapitulatif final", "résumé final", "resume final",
    "conseiller legalplus vous contactera", "conseiller vous contactera",
    "tout est en ordre", "processus est terminé", "processus est termine",
    "toutes les informations nécessaires sont", "toutes les informations necessaires sont",
    "votre demande a été enregistrée", "votre demande a ete enregistree", "félicitations", "felicitations",
]


def check_reply_false_completion(reply, missing_required):
    """
    Catches the reply falsely declaring the workflow complete.

    Deliberately deterministic, not an LLM judgment call: an LLM-judge here
    proved too unreliable in practice — it repeatedly flagged plain
    explanatory replies (e.g. answering "why do you need 3 names?") as false
    completions, with no principled way to distinguish "explaining a
    requirement" from "declaring victory" from a single subjective call.
    A genuine false completion reliably echoes recognizable wrap-up phrasing
    (mirroring the system prompt's own suggested completion wording), so
    keyword matching on that phrasing is narrower but far more precise for
    this specific failure mode.
    """
    if not missing_required:
        return False
    reply_lower = (reply or "").lower()
    return any(signal in reply_lower for signal in FALSE_COMPLETION_SIGNALS)


def build_fallback_reply(core_fields, collected_data, optional_addons=None):
    """Zero-LLM, ground-truth reply — only used if two full attempts both lied."""
    missing = missing_required_fields(core_fields, collected_data)
    if missing:
        next_field = next((f for f in core_fields if f["name"] == missing[0]), None)
        return next_field["question"] if next_field else "Pouvez-vous préciser cette information ?"
    if optional_addons:
        for addon in optional_addons:
            if not collected_data.get(addon["name"]):
                return addon["question"]
    return "Merci, toutes les informations nécessaires sont bien enregistrées. Un conseiller LegalPlus vous contactera bientôt."


def run_agent_turn(core_fields, collected_data, conversation_history, user_message, optional_addons=None):
    """
    Fully LLM-driven: the model decides which tool (if any) to call, every
    turn, with tool_choice="auto" — no field is pre-extracted or
    pre-decided by code, and we never force a tool call. Forcing a call
    when nothing valid is in the message (tried previously via
    tool_choice="required" on retry) turned out to actively cause
    fabricated saves — the model has to call SOMETHING, so it grabs
    whatever's lying around. That's worse than just asking again.

    So: one attempt, tool_choice="auto". If the reply is caught lying
    (narrating an unsaved save, or falsely claiming completion), we
    discard it and use a deterministic, ground-truth fallback question —
    safe, honest, never forces a bad write.
    """
    status = get_workflow_status(core_fields, collected_data, optional_addons)
    system_prompt = build_system_prompt(status)
    messages = [{"role": "system", "content": system_prompt}] + FEW_SHOT_EXAMPLES + conversation_history + [
        {"role": "user", "content": user_message}
    ]

    response = client.chat.completions.create(model="gpt-4o-mini", messages=messages, tools=tools, tool_choice="auto")
    message = response.choices[0].message
    tools_used = []

    if message.tool_calls:
        tool_responses = execute_tool_calls(message.tool_calls, core_fields, optional_addons, collected_data, user_message)
        for tc, tr in zip(message.tool_calls, tool_responses):
            tools_used.append({"tool": tc.function.name, "arguments": json.loads(tc.function.arguments), "result": tr["content"]})
        second_response = client.chat.completions.create(model="gpt-4o-mini", messages=messages + [message] + tool_responses)
        reply = second_response.choices[0].message.content
    else:
        reply = message.content

    still_missing = missing_required_fields(core_fields, collected_data)

    # false_completion is now a cheap, deterministic keyword check — safe to
    # always run. mismatch is still an LLM judgment call, so it stays gated
    # to declarative (non-question) replies, where it has a real shot at
    # being right — see comments on both functions above for why.
    false_completion = check_reply_false_completion(reply, still_missing)

    reply_is_a_question = "?" in (reply or "")
    mismatch = False
    if not reply_is_a_question and not false_completion:
        mismatch = check_reply_matches_saved_data(user_message, reply, collected_data)

    if mismatch or false_completion:
        reason = "mismatch (claimed a save that isn't in collected_data)" if mismatch else "false completion (declared done while fields are missing)"
        print(f"[debug — fallback triggered ({reason}); discarded reply: {reply!r}]")
        reply = build_fallback_reply(core_fields, collected_data, optional_addons)

    conversation_history.append({"role": "user", "content": user_message})
    conversation_history.append({"role": "assistant", "content": reply})

    return reply, tools_used


if __name__ == "__main__":
    config_filename = sys.argv[1] if len(sys.argv) > 1 else "fields_sarl.json"

    with open(config_filename, "r", encoding="utf-8") as f:
        config = json.load(f)

    core_fields = config["core_fields"]
    optional_addons = config["optional_addons"]

    collected_data = {}
    conversation_history = []

    conversation_id = start_conversation(user_id="test_user_1", title="Création SARL")

    print("=" * 50)
    print("👋 Bienvenue chez LegalPlus AI")
    print("=" * 50)

    print("\nAI: Avant de commencer, quel est votre email ?")
    email = None
    while email is None:
        user_input = input("You: ").strip()
        email = validate_email(user_input)
        if email is None:
            print("AI: Cet email ne semble pas valide. Pouvez-vous le vérifier et le redonner ?")

    collected_data["email"] = email
    save_message(conversation_id, "user", user_input)
    save_message(conversation_id, "assistant", "Email enregistré.", meta={"tools_used": [{"tool": "validate_email", "result": email}]})
    print(f"AI: Merci ! Email enregistré : {email}\n")

    all_addon_names = [a["name"] for a in optional_addons]

    while True:
        user_message = input("You: ")
        reply, tools_used = run_agent_turn(core_fields, collected_data, conversation_history, user_message, optional_addons)
        print(f"AI: {reply}")
        print(f"[state: {collected_data}]")

        save_message(conversation_id, "user", user_message)
        save_message(conversation_id, "assistant", reply, meta={"tools_used": tools_used} if tools_used else None)

        addons_covered = all(name in collected_data for name in all_addon_names)
        still_missing = missing_required_fields(core_fields, collected_data)
        required_done = not still_missing

        if not required_done:
            print(f"[debug — still genuinely missing: {still_missing}]")

        if required_done and addons_covered:
            print("\n📋 Résumé final :")
            print(json.dumps(collected_data, indent=2, ensure_ascii=False))

            import datetime

            draft_id = datetime.datetime.now().strftime("%Y%m%d_%H%M%S")
            collected_data["draft_id"] = draft_id
            collected_data["workflow"] = config_filename.replace("fields_", "").replace(".json", "")
            collected_data["created_at"] = datetime.datetime.now().isoformat()

            all_drafts = []
            if os.path.exists("draft_output.json"):
                try:
                    with open("draft_output.json", "r", encoding="utf-8") as f:
                        existing_content = json.load(f)
                        if isinstance(existing_content, list):
                            all_drafts = existing_content
                        else:
                            all_drafts = [existing_content]
                except (json.JSONDecodeError, ValueError):
                    all_drafts = []

            all_drafts.append(collected_data)

            with open("draft_output.json", "w", encoding="utf-8") as f:
                json.dump(all_drafts, f, indent=2, ensure_ascii=False)

            print(f"\n✅ Votre demande a été enregistrée (draft_id: {draft_id}).")
            print(f"Total de demandes enregistrées jusqu'à présent: {len(all_drafts)}")

            break