# Public Intelligence Node API

## Overview

The Public Intelligence Node exposes a local HTTP API for inference while communicating with the Scheduler through its REST API.

The Node has two forms of communication:

1. Incoming requests from Clients.
2. Outgoing requests to the Scheduler.

The Node never performs scheduling.

The Scheduler never performs inference.

---

# Local Node API

The following endpoints are exposed by every Node.

---

## POST /infer

Execute inference using a locally hosted model.

### Request

```json
{
  "model": "llama3-8b",
  "prompt": "Explain black holes."
}
```

### Response

```json
{
  "model": "llama3-8b",
  "response": "Black holes are..."
}
```

### Errors

400 Bad Request

Invalid request.

404 Not Found

Requested model is not hosted by this Node.

500 Internal Server Error

Inference execution failed.

---

## GET /health

Returns the current health status of the Node and its connection to the local Ollama server.

### Response (Healthy)

```json
{
  "status": "healthy",
  "ollama": true
}
```

### Response (Degraded - Ollama offline)

```json
{
  "status": "degraded",
  "ollama": false
}
```

Purpose:

- Liveness checks
- Monitoring
- Local diagnostics

---

## GET /models

Returns every model currently hosted by the Node.

### Response

```json
[
  {
    "name": "llama3-8b"
  },
  {
    "name": "mistral-7b"
  }
]
```

Purpose:

- Local inspection
- Debugging
- Future tooling

---

# Scheduler Communication

The Node communicates with the Scheduler using the Scheduler's public API.

The Scheduler remains the source of truth for network state.

---

## Registration

During startup the Node performs:

```
POST /nodes/register
```

The request contains:

- Node ID
- Hostname
- Region
- IP Address
- Hardware information
- Hosted models

Registration occurs once during startup.

---

## Heartbeats

After successful registration the Node periodically sends:

```
POST /heartbeat
```

Heartbeat data includes:

- Queue length
- CPU utilization
- GPU utilization
- Available VRAM
- Available RAM
- Status
- Timestamp

Heartbeats allow the Scheduler to maintain an accurate view of runtime state.

---

## Graceful Shutdown

When possible the Node should notify the Scheduler before shutting down.

```
DELETE /nodes/{node_id}
```

If graceful shutdown is not possible, the Scheduler will eventually detect the missing heartbeats and consider the Node unavailable.

---

# API Philosophy

The Node API should remain extremely small.

Business logic belongs inside the underlying components.

Endpoints should only:

- Validate requests.
- Delegate work.
- Return responses.

No scheduling logic should exist inside the Node API.

---

# Versioning

Version 1.0 exposes only three local endpoints:

- POST /infer
- GET /health
- GET /models

Future versions may introduce additional endpoints, but Version 1.0 intentionally keeps the API minimal.

---

# Error Handling

The API should use standard HTTP status codes.

| Status | Meaning |
|---------|---------|
| 200 | Success |
| 400 | Invalid request |
| 404 | Resource not found |
| 409 | Conflict |
| 500 | Internal server error |

Responses should be deterministic and human-readable.

---

# Security

Version 1.0 does not implement:

- Authentication
- Authorization
- TLS
- Rate limiting

These capabilities belong to future versions of Public Intelligence.

The initial focus is functional correctness and simplicity.