import uuid

from workflow_store import (
    create_workflow_state,
    load_workflow_state,
    save_workflow_state
)

cid = str(uuid.uuid4())

create_workflow_state(cid, "SARL")

print(load_workflow_state(cid))

data = load_workflow_state(cid)

data["manager_name"] = "Houda"

save_workflow_state(cid, data)

print(load_workflow_state(cid))