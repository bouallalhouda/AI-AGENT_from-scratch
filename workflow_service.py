"""
Orchestration layer between agent_loop.py and the two stores.

agent_loop.py should only ever call functions in this file for anything
persistence-related -- it should never import conversation_store or
workflow_store directly. That's what keeps adding a new workflow type
(trademark, SAS, ...) from turning into edits scattered across the agent.
"""

from conversation_store import start_conversation, save_message
from workflow_store import (
    load_workflow_state,
    update_workflow_field,
    set_last_step,
    find_active_workflow_for_user,
    mark_workflow_completed,
)


def resume_or_create_workflow(user_id, workflow, title=None):
    """
    Looks for an ACTIVE workflow of this type for this user and resumes it.
    Otherwise starts a new conversation + workflow_state.

    Returns (conversation_id, state, last_step, is_resumed).
    """
    existing = find_active_workflow_for_user(user_id, workflow=workflow)

    if existing:
        return (
            existing["conversation_id"],
            existing["state"] or {},
            existing["last_step"],
            True,
        )

    conversation_id = start_conversation(
        user_id, title=title or workflow, workflow=workflow
    )
    return conversation_id, {}, None, False


def save_field(conversation_id, field, value):
    """Persists one field immediately. Mirrors doc's point 3 -- never batched."""
    return update_workflow_field(conversation_id, field, value)


def record_last_step(conversation_id, step):
    set_last_step(conversation_id, step)


def get_current_state(conversation_id):
    return load_workflow_state(conversation_id)


def mark_completed(conversation_id):
    mark_workflow_completed(conversation_id)


def log_message(conversation_id, role, content, meta=None):
    save_message(conversation_id, role, content, meta=meta)
