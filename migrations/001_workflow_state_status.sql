-- workflow_state needs to know if it's still being filled out or done,
-- so we can (a) resume the right one and (b) stop relying on draft_output.json.
-- Nothing changes on `conversations` -- it stays a plain thread table
-- (id, user_id, title, ...), matching what's actually in the DB.

ALTER TABLE workflow_state
    ADD COLUMN IF NOT EXISTS status TEXT NOT NULL DEFAULT 'active',
    ADD COLUMN IF NOT EXISTS ended_at TIMESTAMPTZ;

-- "one active workflow per user" is enforced in application code
-- (resume_or_create_workflow), not the DB, since it needs the join to
-- conversations.user_id -- a DB constraint here would need workflow_state
-- to duplicate user_id onto itself just to index it, which isn't worth it
-- unless we see real data-integrity problems from concurrent writes.