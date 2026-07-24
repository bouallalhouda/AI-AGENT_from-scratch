import os
import uuid
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv
from workflow_store import create_workflow_state
load_dotenv()


def get_connection():
    return psycopg2.connect(
        host=os.getenv("KB_DB_HOST", "localhost"),
        port=os.getenv("KB_DB_PORT", "5432"),
        dbname=os.getenv("KB_DB_NAME", "legalplus"),
        user=os.getenv("KB_DB_USER", "postgres"),
        password=os.getenv("KB_DB_PASSWORD"),
    )

def start_conversation(user_id, title, workflow="SARL"):
    """
    Creates a new conversation and its workflow_state.
    Returns the conversation_id.
    """
    conversation_id = str(uuid.uuid4())

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO conversations
                (id, user_id, title, created_at, updated_at, last_message_at)
                VALUES (%s, %s, %s, now(), now(), now());
                """,
                (conversation_id, user_id, title),
            )

        conn.commit()

    finally:
        conn.close()

    # Create the workflow memory for this conversation
    create_workflow_state(
        conversation_id=conversation_id,
        workflow=workflow
    )

    return conversation_id

def save_message(conversation_id, role, content, parent_id=None, meta=None):
    """
    Inserts one message row into `messages`, linked to a conversation.
    role should be 'user' or 'assistant'.
    """
    message_id = str(uuid.uuid4())

    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO messages (id, conversation_id, parent_id, role, content, meta, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, %s, now(), now());
                """,
                (message_id, conversation_id, parent_id, role, content, psycopg2.extras.Json(meta) if meta else None),
            )
            cur.execute(
                "UPDATE conversations SET last_message_at = now(), updated_at = now() WHERE id = %s;",
                (conversation_id,),
            )
        conn.commit()
    finally:
        conn.close()

    return message_id