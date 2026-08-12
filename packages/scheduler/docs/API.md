# Scheduler API

## Health

GET /health

Returns scheduler liveness.

---

GET /health/ready

Returns scheduler readiness.

---

GET /status

Returns the Scheduler operational state, Zenoh transport state, registered
nodes, and each node's latest heartbeat summary.

---

## Nodes

POST /nodes/register

Register a compute node.

Headers:
- `X-Network-Auth-Token`: the fleet's shared **admission** secret (required if the
  Scheduler configures one). Compared against it and never retained.
- `X-Node-Credential`: **this node's own** secret. Stored, never compared, and used
  afterwards to authenticate to the node's control API and to verify the mesh
  envelopes it seals. Optional: when absent the admission token is stored instead,
  which is what every node did before decision D9 and is why upgrading a Scheduler
  does not strand an already-registered fleet.
- `X-Invite-Code`: required if the Scheduler has issued any (decision D4).

The two are separate headers because one value cannot both equal a secret every host
shares and identify one host. See `docs/decisions/D9-admission-is-not-identity.md`.

Request body: Node

Returns: Node (HTTP 201 Created)

Duplicate node_id returns HTTP 409 Conflict. The credential is recorded before that
check, so a node whose secret has rotated refreshes it even when the call 409s.

---

GET /nodes

List all registered nodes.

Returns: list[Node] (HTTP 200)

---

GET /nodes/{node_id}

Get a specific node by ID.

Returns: Node (HTTP 200)

Missing node returns HTTP 404.

---

DELETE /nodes/{node_id}

Unregister a node during graceful shutdown.

---

## Heartbeat

POST /heartbeat

Update node runtime status and resource utilization metrics.

Headers:
- `X-Network-Auth-Token`: The secure network authentication token (required if configured)

Request body: Heartbeat

Returns: {"status": "ok"} (HTTP 200 OK)

If the node is not registered, returns HTTP 404 Not Found.

---

## Schedule

POST /schedule

Find the best eligible compute node for running a requested model.

Headers:
- `X-Network-Auth-Token`: The secure network authentication token (required if configured)

Request body: ScheduleRequest (with field model_name: str)

Returns: ScheduleResponse (with fields node_id, hostname, ip_address, region) (HTTP 200 OK)

If no eligible node is found or registered, returns HTTP 404 Not Found.

---

POST /infer

Select an eligible node and forward one non-streaming inference request to its
Node API. Returns the selected `node_id` and the Node's inference result.

If the Node is unavailable, returns HTTP 502 Bad Gateway.

---

## Planned APIs

POST /forward

Forward inference request to selected node.
