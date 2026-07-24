import os
import json
import psycopg2
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


def create_workflow_state(conversation_id, workflow):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                INSERT INTO workflow_state
                (conversation_id, workflow_name, json_data, last_step, status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, 'active', now(), now())
                ON CONFLICT (conversation_id)
                DO NOTHING;
                """,
                (
                    conversation_id,
                    workflow,
                    json.dumps({}),
                    None,
                ),
            )
        conn.commit()
    finally:
        conn.close()


def load_workflow_state(conversation_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                SELECT json_data
                FROM workflow_state
                WHERE conversation_id=%s;
                """,
                (conversation_id,),
            )

            row = cur.fetchone()

            if row is None:
                return {}

            return row[0] or {}

    finally:
        conn.close()


def save_workflow_state(conversation_id, state):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workflow_state
                SET
                    json_data=%s,
                    updated_at=now()
                WHERE conversation_id=%s;
                """,
                (
                    json.dumps(state),
                    conversation_id,
                ),
            )

        conn.commit()

    finally:
        conn.close()


def update_workflow_field(conversation_id, field, value):
    state = load_workflow_state(conversation_id)

    state[field] = value

    save_workflow_state(conversation_id, state)

    return state


def set_last_step(conversation_id, step):
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workflow_state
                SET
                    last_step=%s,
                    updated_at=now()
                WHERE conversation_id=%s;
                """,
                (
                    step,
                    conversation_id,
                ),
            )

        conn.commit()

    finally:
        conn.close()

def find_active_workflow_for_user(user_id, workflow=None):
    """
    Returns the latest ACTIVE workflow_state for this user (matched via
    conversations.user_id -- the only identifying column that actually
    exists on `conversations`). Optionally filtered to one workflow type,
    since a user can have an active SARL creation and an active trademark
    request at the same time (doc's point 8/9).
    """
    conn = get_connection()

    try:
        with conn.cursor() as cur:
            query = """
                SELECT
                    ws.conversation_id,
                    ws.workflow_name,
                    ws.json_data,
                    ws.last_step
                FROM workflow_state ws
                JOIN conversations c
                    ON ws.conversation_id = c.id
                WHERE
                    c.user_id = %s
                    AND ws.status = 'active'
            """
            params = [user_id]

            if workflow is not None:
                query += " AND ws.workflow_name = %s"
                params.append(workflow)

            query += " ORDER BY ws.updated_at DESC LIMIT 1;"

            cur.execute(query, params)
            row = cur.fetchone()

            if row is None:
                return None

            return {
                "conversation_id": row[0],
                "workflow": row[1],
                "state": row[2],
                "last_step": row[3],
            }

    finally:
        conn.close()


def mark_workflow_completed(conversation_id):
    conn = get_connection()
    try:
        with conn.cursor() as cur:
            cur.execute(
                """
                UPDATE workflow_state
                SET status='completed', ended_at=now(), updated_at=now()
                WHERE conversation_id=%s;
                """,
                (conversation_id,),
            )
        conn.commit()
    finally:
        conn.close()