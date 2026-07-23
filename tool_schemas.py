tools = [
    {
        "type": "function",
        "function": {
            "name": "validate_moroccan_phone",
            "description": "Call this the moment the user gives a phone number, to validate it and save it. Always call this immediately when a phone number appears in the user's message.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "phone_number": {
                        "type": "string",
                        "description": "The phone number exactly as given by the user."
                    }
                },
                "required": ["phone_number"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "update_field",
            "description": "Call this the moment you have a confirmed value for activity, associate_name, manager_name, or an optional addon (domiciliation, comptabilite). Do NOT use for phone numbers, company names, or signature type — those have their own tools.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "field_name": {
                        "type": "string",
                        "description": "The exact field name, e.g. 'activity', 'associate_name', 'manager_name', 'domiciliation', 'comptabilite'."
                    },
                    "new_value": {
                        "type": "string",
                        "description": "The value the user gave for this field."
                    }
                },
                "required": ["field_name", "new_value"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "set_signature_type",
            "description": "Call this the moment the user has chosen between separate and joint signature.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "value": {
                        "type": "string",
                        "enum": ["separate", "joint"],
                        "description": "Must be exactly 'separate' or 'joint'."
                    }
                },
                "required": ["value"],
                "additionalProperties": False
            }
        }
    },
    {
        "type": "function",
        "function": {
            "name": "add_company_names",
            "description": "Call this every time the user proposes one or more company names, immediately in the same turn. Pass ALL names given in this message, even if it's just one. Call again each time more names are given, until 3 total are collected.",
            "strict": True,
            "parameters": {
                "type": "object",
                "properties": {
                    "names": {
                        "type": "array",
                        "items": {"type": "string"},
                        "description": "One or more company names the user just proposed in this message."
                    }
                },
                "required": ["names"],
                "additionalProperties": False
            }
        }
    }
]
