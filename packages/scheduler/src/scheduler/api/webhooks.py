"""GitHub issue webhook ingestion endpoints (/v1/webhooks/github)."""

import uuid
from typing import Any

from fastapi import APIRouter, Depends, Header, status
from pydantic import BaseModel, Field

from scheduler.api.auth import verify_auth_token
from scheduler.core.autonomous_orchestrator import AutonomousOrchestrator, MissionResult

# NOT MOUNTED: `create_app` does not include this router, so these paths 404 today.
# Guarded anyway, so that mounting it is a one-line change that does not also open
# an anonymous POST. The proper control for a GitHub webhook is X-Hub-Signature-256
# HMAC verification, which needs a shared secret nothing here provisions -- recorded
# in specs/authenticate-the-read-surface.md rather than half-built.
router = APIRouter(
    prefix="/v1/webhooks",
    tags=["webhooks"],
    dependencies=[Depends(verify_auth_token)],
)

_orchestrator = AutonomousOrchestrator()


class GitHubIssuePayload(BaseModel):
    """Payload format for incoming GitHub issue webhooks."""

    action: str = Field(description="Action name e.g. opened, labeled")
    issue: dict[str, Any] = Field(description="Issue object data")


@router.post(
    "/github",
    response_model=MissionResult,
    status_code=status.HTTP_202_ACCEPTED,
)
async def process_github_issue_webhook(
    payload: GitHubIssuePayload,
    # Declared but unread: FastAPI needs the parameter to document and validate the
    # header, and GitHub always sends it. Reading it would mean dispatching on event
    # type, which this endpoint does not do.
    x_github_event: str = Header("issues", alias="X-GitHub-Event"),  # noqa: ARG001
) -> MissionResult:
    """Ingest GitHub issue webhook from n8n automation and launch autonomous mission."""
    issue_data = payload.issue
    issue_number = str(issue_data.get("number", "100"))
    issue_title = issue_data.get("title", "Autonomous Task")
    issue_body = issue_data.get("body", "")

    mission_id = f"mission_{uuid.uuid4().hex[:12]}"
    prompt = f"{issue_title}: {issue_body}"

    return await _orchestrator.execute_mission(
        mission_id=mission_id,
        prompt=prompt,
        issue_id=f"#{issue_number}",
    )
