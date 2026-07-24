from workflow_store import (
    get_workflow_state,
    create_workflow_state,
)


def load_state(conversation_id: str, workflow: str):
    """
    Returns the current workflow state.
    Creates one if it doesn't exist.
    """

    state = get_workflow_state(conversation_id)

    if state is None:
        create_workflow_state(conversation_id, workflow)
        state = get_workflow_state(conversation_id)

    return state
from workflow_store import update_field


def save_field(conversation_id, field_name, value):
    """
    Save one field immediately.
    """

    update_field(
        conversation_id=conversation_id,
        field_name=field_name,
        value=value,
    )