from tools import signature_type_applicable
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
