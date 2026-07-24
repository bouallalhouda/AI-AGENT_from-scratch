import re


def validate_moroccan_phone(phone):
    """
    Validates a Moroccan phone number.
    Accepts formats like: 0612345678, +212612345678, 212612345678
    Returns cleaned number or None if invalid.
    """
    cleaned = re.sub(r"[\s\-\.]", "", phone)

    patterns = [
        r"^0[5-7]\d{8}$",
        r"^\+212[5-7]\d{8}$",
        r"^212[5-7]\d{8}$",
    ]

    for pattern in patterns:
        if re.match(pattern, cleaned):
            return cleaned
    return None


def validate_email(email):
    """
    Basic email format validation. Returns cleaned email or None if invalid.
    """
    email = email.strip()
    pattern = r"^[^@\s]+@[^@\s]+\.[^@\s]+$"
    if re.match(pattern, email):
        return email
    return None


RESTRICTED_FIELDS = {"company_name_choices", "signature_type", "associate_phone"}


def update_field(field_name, new_value, core_fields, collected_data):
    """
    Updates a field's value, but ONLY if field_name is a real field
    from core_fields, and NOT one of the fields that has its own dedicated tool.
    """
    if field_name in RESTRICTED_FIELDS:
        return False

    valid_field_names = [field["name"] for field in core_fields]

    if field_name not in valid_field_names:
        return False

    collected_data[field_name] = new_value
    return True


def set_signature_type(value, collected_data):
    """
    Sets signature_type, but only accepts 'separate' or 'joint'.
    """
    if value not in ("separate", "joint"):
        return False
    collected_data["signature_type"] = value
    return True


def add_company_names(names, collected_data):
    """
    Adds one or more proposed company names to collected_data,
    merging with any already saved, avoiding duplicates.
    Returns the current count and whether 3 names have been reached.
    """
    existing = collected_data.get("company_name_choices", [])
    existing_lower = [n.lower() for n in existing]

    for name in names:
        if name.lower() not in existing_lower:
            existing.append(name)
            existing_lower.append(name.lower())

    collected_data["company_name_choices"] = existing

    return {
        "count": len(existing),
        "complete": len(existing) >= 3,
        "names_so_far": existing
    }


def signature_type_applicable(collected_data):
    """
    Signature type (separate vs joint) only makes sense if the manager
    and the associate are two different people. If they're the same
    person, there's nothing to separate/join, so the question doesn't apply.
    """
    manager = collected_data.get("manager_name")
    associate = collected_data.get("associate_name")
    if not manager or not associate:
        return True  # not enough info yet, assume it's needed for now
    return manager.strip().lower() != associate.strip().lower()


def apply_signature_rule(collected_data):
    """
    If manager and associate are the same person,
    automatically use separate signature.
    Returns True only if something changed.
    """

    associate = (collected_data.get("associate_name") or "").strip().lower()
    manager = (collected_data.get("manager_name") or "").strip().lower()

    if not associate or not manager:
        return False

    if associate == manager:
        if collected_data.get("signature_type") != "separate":
            collected_data["signature_type"] = "separate"
            return True

    return False