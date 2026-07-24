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
                (conversation_id, workflow, json_data, last_step, created_at, updated_at)
                VALUES (%s, %s, %s, %s, now(), now())
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

def find_open_workflow_by_email(email):
    """
    Returns the latest unfinished workflow for this email.
    """

    conn = get_connection()

    try:
        with conn.cursor() as cur:

            cur.execute(
                """
                SELECT
                    ws.conversation_id,
                    ws.workflow,
                    ws.json_data,
                    ws.last_step
                FROM workflow_state ws
                JOIN conversations c
                    ON ws.conversation_id = c.id
                WHERE
                    c.user_id = %s
                ORDER BY ws.updated_at DESC
                LIMIT 1;
                """,
                (email,),
            )

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