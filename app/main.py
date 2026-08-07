from __future__ import annotations

import asyncio
import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID
from uuid import uuid4

import os

from fastapi import Depends, FastAPI, File, Form, Header, HTTPException, Response, UploadFile
from fastapi.responses import FileResponse, StreamingResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware

from app.domain.models import (
    AssistantMessage,
    AuditEvent,
    Conversation,
    CreateNousActionRequest,
    CreateNousPlanRequest,
    CreateConversationRequest,
    GoalScenarioRequest,
    MessageRole,
    Product,
    ProposalStatus,
    SaveJobDescriptionRequest,
    SendMessageRequest,
    UpdateProposalRequest,
)
from app.services.assistant import assistant_provider
from app.services.auth import Identity, issue_token, require_conversation_access, require_identity
from app.services.financial_imports import (
    MAX_CSV_BYTES,
    accounts_template,
    parse_accounts,
    parse_transactions,
    transactions_template,
)
from app.services.store import store
from app.services.plutus import PlutusService
from app.services.nous import NousService
from app.services.runtime import RuntimeMiddleware, current_request_id
from app.services.resume_documents import MAX_UPLOAD_BYTES, export_resume_docx, read_upload
from app.services.source_ingestion import MAX_SOURCE_BYTES, SourceUpload, parse_sources
from app.services.settings import settings
from app.services.tyche import TycheService

app = FastAPI(title="Parallel Copilots", version="0.9.0")
app.add_middleware(
    RuntimeMiddleware,
    request_limit_per_minute=settings.request_limit_per_minute,
    secure_environment=settings.app_env in {"demo", "production"},
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts))
static_dir = Path(__file__).parent / "static"
app.mount("/static", StaticFiles(directory=static_dir), name="static")
tyche_service = TycheService(store)
plutus_service = PlutusService(store)
nous_service = NousService(store)
logger = logging.getLogger("parallel_copilots")


def ensure_feature(product: Product) -> None:
    if not settings.feature_enabled(product):
        raise HTTPException(status_code=404, detail="Capability not available")


@app.get("/", include_in_schema=False)
async def index() -> FileResponse:
    return FileResponse(static_dir / "index.html")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {
        "status": "ok",
        "provider": assistant_provider.__class__.__name__,
        "store": store.__class__.__name__,
        "auth_mode": os.getenv("AUTH_MODE", "local"),
        "version": app.version,
    }


@app.get("/api/config")
async def public_config() -> dict:
    return {
        "features": settings.public_features(),
        "version": app.version,
        "browser_auth_mode": settings.browser_auth_mode(),
    }


@app.post("/api/auth/dev-token")
async def create_dev_token() -> dict[str, str]:
    if settings.browser_auth_mode() != "development":
        raise HTTPException(status_code=404, detail="Not found")
    identity = Identity(user_id="demo-user", workspace_id="demo-workspace")
    return {"access_token": issue_token(identity), "token_type": "bearer"}


@app.post("/api/auth/guest-token")
async def create_guest_token() -> dict[str, str]:
    if settings.browser_auth_mode() != "guest":
        raise HTTPException(status_code=404, detail="Not found")
    guest_id = f"guest-{uuid4()}"
    identity = Identity(user_id=guest_id, workspace_id=guest_id)
    return {
        "access_token": issue_token(identity, ttl_seconds=24 * 60 * 60),
        "token_type": "bearer",
    }


@app.post("/api/conversations", response_model=Conversation, status_code=201)
async def create_conversation(
    request: CreateConversationRequest, identity: Identity = Depends(require_identity)
) -> Conversation:
    ensure_feature(request.product)
    conversation = Conversation(
        product=request.product,
        workspace_id=identity.workspace_id,
        owner_user_id=identity.user_id,
    )
    store.save_conversation(conversation)
    store.audit(
        AuditEvent(
            conversation_id=conversation.id,
            workspace_id=identity.workspace_id,
            actor="user",
            event_type="conversation.created",
            data={"product": request.product.value},
        )
    )
    return conversation


@app.get("/api/conversations/{conversation_id}", response_model=Conversation)
async def get_conversation(
    conversation_id: UUID, identity: Identity = Depends(require_identity)
) -> Conversation:
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    ensure_feature(conversation.product)
    return conversation


@app.delete("/api/conversations/{conversation_id}", status_code=204)
async def delete_conversation(
    conversation_id: UUID, identity: Identity = Depends(require_identity)
) -> Response:
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    store.delete_conversation(conversation_id)
    return Response(status_code=204)


@app.post("/api/conversations/{conversation_id}/messages")
async def send_message(
    conversation_id: UUID,
    request: SendMessageRequest,
    identity: Identity = Depends(require_identity),
) -> StreamingResponse:
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    ensure_feature(conversation.product)
    if request.context.product != conversation.product:
        raise HTTPException(status_code=409, detail="Context product does not match conversation")

    request.context.workspace_id = identity.workspace_id
    request.context.created_by = identity.user_id
    request.context = tyche_service.prepare_context(identity, request.context)
    request.context = plutus_service.prepare_context(identity, request.context)
    request.context = nous_service.prepare_context(identity, request.context)
    store.save_context(conversation_id, request.context)
    user_message = AssistantMessage(
        conversation_id=conversation_id,
        role=MessageRole.USER,
        content=request.content,
        context_snapshot_id=request.context.id,
    )
    conversation.messages.append(user_message)
    conversation.updated_at = datetime.now(timezone.utc)
    store.save_conversation(conversation)
    store.audit(
        AuditEvent(
            conversation_id=conversation_id,
            workspace_id=identity.workspace_id,
            actor="user",
            event_type="message.sent",
            data={"message_id": str(user_message.id), "context_id": str(request.context.id)},
        )
    )

    request_id = current_request_id()

    async def stream():
        try:
            result = await assistant_provider.respond(request.content, request.context)
            words = result.content.split(" ")
            for word in words:
                yield json.dumps({"type": "delta", "text": word + " "}) + "\n"
                await asyncio.sleep(0.018)

            assistant_message = AssistantMessage(
                conversation_id=conversation_id,
                role=MessageRole.ASSISTANT,
                content=result.content,
                context_snapshot_id=request.context.id,
                evidence=result.evidence,
                proposals=result.proposals,
            )
            conversation.messages.append(assistant_message)
            conversation.updated_at = datetime.now(timezone.utc)
            for proposal in result.proposals:
                store.save_proposal(conversation_id, proposal)
            store.save_conversation(conversation)
            store.audit(
                AuditEvent(
                    conversation_id=conversation_id,
                    workspace_id=identity.workspace_id,
                    actor="assistant",
                    event_type="message.completed",
                    data={
                        "message_id": str(assistant_message.id),
                        "evidence_count": len(result.evidence),
                        "proposal_ids": [str(p.id) for p in result.proposals],
                        "provider": result.provider_name,
                        "model": result.model,
                        "prompt_version": result.prompt_version,
                        "provider_response_id": result.response_id,
                        "usage": result.usage,
                        "request_id": request_id,
                    },
                )
            )
            yield json.dumps({"type": "complete", "message": assistant_message.model_dump(mode="json")}) + "\n"
        except Exception:
            logger.exception("assistant_response_failed", extra={"request_id": request_id})
            yield json.dumps({"type": "error", "message": "The assistant could not complete this response."}) + "\n"

    return StreamingResponse(stream(), media_type="application/x-ndjson")


@app.post("/api/proposals/{proposal_id}")
async def update_proposal(
    proposal_id: UUID,
    request: UpdateProposalRequest,
    identity: Identity = Depends(require_identity),
    idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
) -> dict:
    found = store.get_proposal(proposal_id)
    if not found:
        raise HTTPException(status_code=404, detail="Proposal not found")
    conversation_id, proposal = found
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Proposal not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    ensure_feature(conversation.product)
    if (
        request.action == "apply"
        and proposal.status == ProposalStatus.APPLIED
        and idempotency_key
        and proposal.applied_idempotency_key == idempotency_key
    ):
        return {"proposal": proposal.model_dump(mode="json"), "idempotent_replay": True}
    if proposal.status not in {ProposalStatus.PRESENTED, ProposalStatus.EDITED}:
        raise HTTPException(status_code=409, detail="Proposal is no longer actionable")
    if request.source_version != proposal.source_version:
        raise HTTPException(status_code=409, detail="The source changed; generate a fresh proposal")

    tyche_workspace = None
    tyche_change = None
    plutus_workspace = None
    nous_workspace = None
    if request.action == "cancel":
        if proposal.payload.get("nous_managed"):
            nous_workspace = nous_service.cancel_external_action(identity, proposal)
        proposal.status = ProposalStatus.CANCELLED
    elif request.action == "edit":
        if not request.suggested_text or not proposal.diff:
            raise HTTPException(status_code=422, detail="Edited text is required")
        proposal.diff.suggested = request.suggested_text
        proposal.status = ProposalStatus.EDITED
    else:
        if not idempotency_key:
            raise HTTPException(status_code=400, detail="Idempotency-Key is required when applying")
        if proposal.payload.get("tyche_managed") and proposal.diff:
            tyche_workspace, tyche_change = tyche_service.apply_proposal(
                identity, proposal, proposal.diff.suggested
            )
        if proposal.payload.get("plutus_managed"):
            plutus_workspace = plutus_service.apply_goal(identity, proposal)
        if proposal.payload.get("nous_managed"):
            nous_workspace = nous_service.apply_external_action(identity, proposal)
        proposal.status = ProposalStatus.APPLIED
        proposal.applied_idempotency_key = idempotency_key

    store.save_proposal(conversation_id, proposal)
    store.audit(
        AuditEvent(
            conversation_id=conversation_id,
            workspace_id=identity.workspace_id,
            actor="user",
            event_type=f"proposal.{request.action}",
            data={
                "proposal_id": str(proposal.id),
                "status": proposal.status.value,
                "tyche_change_id": str(tyche_change.id) if tyche_change else None,
            },
        )
    )
    response = {"proposal": proposal.model_dump(mode="json")}
    if tyche_workspace and tyche_change:
        response["workspace"] = tyche_workspace.model_dump(mode="json")
        response["undo_change_id"] = str(tyche_change.id)
    if plutus_workspace:
        response["workspace"] = plutus_workspace.model_dump(mode="json")
    if nous_workspace:
        response["workspace"] = nous_workspace.model_dump(mode="json")
    return response


@app.get("/api/tyche/workspace")
async def get_tyche_workspace(identity: Identity = Depends(require_identity)) -> dict:
    ensure_feature(Product.TYCHE)
    workspace = tyche_service.get_or_create_workspace(identity)
    return {"workspace": workspace.model_dump(mode="json")}


async def _bounded_upload(file: UploadFile) -> bytes:
    data = await file.read(MAX_UPLOAD_BYTES + 1)
    await file.close()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="The uploaded file exceeds the 8 MB limit")
    return data


@app.post("/api/tyche/resume/import")
async def import_tyche_resume(
    file: UploadFile = File(...),
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.TYCHE)
    imported = read_upload(await _bounded_upload(file), file.filename)
    workspace = tyche_service.import_resume(identity, imported)
    return {"workspace": workspace.model_dump(mode="json")}


@app.get("/api/tyche/resume/export.docx")
async def export_tyche_resume(
    identity: Identity = Depends(require_identity),
) -> StreamingResponse:
    ensure_feature(Product.TYCHE)
    workspace = tyche_service.get_or_create_workspace(identity)
    payload = export_resume_docx(workspace.resume)
    filename = "".join(
        character if character.isalnum() or character in {"-", "_"} else "-"
        for character in workspace.resume.title
    ).strip("-") or "resume"
    return StreamingResponse(
        iter([payload]),
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={"Content-Disposition": f'attachment; filename="{filename}.docx"'},
    )


@app.put("/api/tyche/job-description")
async def save_tyche_job_description(
    request: SaveJobDescriptionRequest,
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.TYCHE)
    workspace = tyche_service.save_job_description(identity, request)
    return {"workspace": workspace.model_dump(mode="json")}


@app.post("/api/tyche/job-description/import")
async def import_tyche_job_description(
    title: str = Form(..., min_length=1, max_length=200),
    company: str = Form(..., min_length=1, max_length=200),
    file: UploadFile = File(...),
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.TYCHE)
    imported = read_upload(await _bounded_upload(file), file.filename)
    if len(imported.text) < 30:
        raise HTTPException(status_code=422, detail="The job description is too short to analyse")
    if len(imported.text) > 30_000:
        raise HTTPException(status_code=413, detail="Job descriptions are limited to 30,000 characters")
    request = SaveJobDescriptionRequest(title=title, company=company, text=imported.text)
    workspace = tyche_service.save_job_description(identity, request)
    return {"workspace": workspace.model_dump(mode="json"), "source_filename": imported.filename}


@app.post("/api/tyche/changes/{change_id}/undo")
async def undo_tyche_change(
    change_id: UUID, identity: Identity = Depends(require_identity)
) -> dict:
    ensure_feature(Product.TYCHE)
    workspace = tyche_service.undo_change(identity, change_id)
    return {"workspace": workspace.model_dump(mode="json")}


@app.get("/api/plutus/workspace")
async def get_plutus_workspace(identity: Identity = Depends(require_identity)) -> dict:
    ensure_feature(Product.PLUTUS)
    workspace = plutus_service.get_or_create_workspace(identity)
    return {"workspace": workspace.model_dump(mode="json")}


@app.get("/api/plutus/import/templates/accounts.csv")
async def download_accounts_template(
    identity: Identity = Depends(require_identity),
) -> Response:
    ensure_feature(Product.PLUTUS)
    return Response(
        content=accounts_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="plutus-accounts-template.csv"'},
    )


@app.get("/api/plutus/import/templates/transactions.csv")
async def download_transactions_template(
    identity: Identity = Depends(require_identity),
) -> Response:
    ensure_feature(Product.PLUTUS)
    return Response(
        content=transactions_template(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="plutus-transactions-template.csv"'},
    )


async def _bounded_csv(file: UploadFile) -> bytes:
    data = await file.read(MAX_CSV_BYTES + 1)
    await file.close()
    if len(data) > MAX_CSV_BYTES:
        raise HTTPException(status_code=413, detail="CSV files are limited to 2 MB")
    return data


@app.post("/api/plutus/import")
async def import_plutus_records(
    accounts_file: UploadFile | None = File(default=None),
    transactions_file: UploadFile | None = File(default=None),
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.PLUTUS)
    if accounts_file is None and transactions_file is None:
        raise HTTPException(status_code=422, detail="Choose an accounts or transactions CSV")
    accounts = None
    transactions = None
    accounts_filename = None
    transactions_filename = None
    warnings: list[str] = []
    if accounts_file is not None:
        accounts, account_warnings, accounts_filename = parse_accounts(
            await _bounded_csv(accounts_file), accounts_file.filename
        )
        warnings.extend(account_warnings)
    if transactions_file is not None:
        transactions, transaction_warnings, transactions_filename = parse_transactions(
            await _bounded_csv(transactions_file), transactions_file.filename
        )
        warnings.extend(transaction_warnings)
    workspace = plutus_service.replace_records(
        identity,
        accounts,
        transactions,
        accounts_filename=accounts_filename,
        transactions_filename=transactions_filename,
        warnings=warnings,
    )
    return {"workspace": workspace.model_dump(mode="json")}


@app.post("/api/plutus/scenarios")
async def create_plutus_scenario(
    request: GoalScenarioRequest,
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.PLUTUS)
    conversation = store.get_conversation(request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    if conversation.product.value != "plutus":
        raise HTTPException(status_code=409, detail="Scenario requires a Plutus conversation")
    workspace, scenario, proposal = plutus_service.scenario(identity, request)
    store.save_proposal(conversation.id, proposal)
    store.audit(
        AuditEvent(
            conversation_id=conversation.id,
            workspace_id=identity.workspace_id,
            actor="assistant",
            event_type="plutus.scenario.created",
            data={
                "scenario_id": str(scenario.id),
                "proposal_id": str(proposal.id),
                "calculation_version": scenario.calculation_version,
            },
        )
    )
    return {
        "scenario": scenario.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
        "workspace_version": workspace.source_version,
    }


@app.get("/api/nous/workspace")
async def get_nous_workspace(identity: Identity = Depends(require_identity)) -> dict:
    ensure_feature(Product.NOUS)
    workspace = nous_service.get_or_create_workspace(identity)
    return {"workspace": workspace.model_dump(mode="json")}


@app.post("/api/nous/sources/import", status_code=201)
async def import_nous_sources(
    files: list[UploadFile] = File(...),
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.NOUS)
    uploads: list[SourceUpload] = []
    for file in files:
        data = await file.read(MAX_SOURCE_BYTES + 1)
        await file.close()
        if len(data) > MAX_SOURCE_BYTES:
            raise HTTPException(status_code=413, detail=f"{file.filename or 'Source'} exceeds the 2 MB limit")
        uploads.append(SourceUpload(filename=file.filename or "source", data=data))
    sources = parse_sources(uploads)
    workspace = nous_service.add_sources(identity, sources)
    return {
        "workspace": workspace.model_dump(mode="json"),
        "sources": [source.model_dump(mode="json") for source in sources],
    }


@app.post("/api/nous/plans", status_code=201)
async def create_nous_plan(
    request: CreateNousPlanRequest,
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.NOUS)
    conversation = store.get_conversation(request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    if conversation.product.value != "nous":
        raise HTTPException(status_code=409, detail="Plan requires a Nous conversation")
    workspace, plan = nous_service.create_plan(
        identity, conversation.id, request.objective, request.source_ids
    )
    user_message = AssistantMessage(
        conversation_id=conversation.id,
        role=MessageRole.USER,
        content=request.objective,
    )
    assistant_message = AssistantMessage(
        conversation_id=conversation.id,
        role=MessageRole.ASSISTANT,
        content=(
            "I prepared a three-step plan using the Research, Analysis, and Briefing agents. "
            "The authorised inputs and every output will remain reviewable."
        ),
    )
    conversation.messages.extend([user_message, assistant_message])
    conversation.updated_at = datetime.now(timezone.utc)
    store.save_conversation(conversation)
    store.audit(
        AuditEvent(
            conversation_id=conversation.id,
            workspace_id=identity.workspace_id,
            actor="assistant",
            event_type="nous.plan.created",
            data={
                "plan_id": str(plan.id),
                "agent_ids": [step.agent_id for step in plan.steps],
                "source_ids": plan.source_ids,
            },
        )
    )
    return {
        "workspace": workspace.model_dump(mode="json"),
        "plan": plan.model_dump(mode="json"),
        "assistant_message": assistant_message.model_dump(mode="json"),
    }


@app.post("/api/nous/plans/{plan_id}/start")
async def start_nous_plan(
    plan_id: UUID, identity: Identity = Depends(require_identity)
) -> dict:
    ensure_feature(Product.NOUS)
    workspace = nous_service.start_plan(identity, plan_id)
    plan = next(item for item in workspace.plans if item.id == plan_id)
    store.audit(
        AuditEvent(
            conversation_id=plan.conversation_id,
            workspace_id=identity.workspace_id,
            actor="user",
            event_type="nous.plan.started",
            data={"plan_id": str(plan.id)},
        )
    )
    return {"workspace": workspace.model_dump(mode="json")}


@app.post("/api/nous/plans/{plan_id}/advance")
async def advance_nous_plan(
    plan_id: UUID, identity: Identity = Depends(require_identity)
) -> dict:
    ensure_feature(Product.NOUS)
    workspace = nous_service.advance_plan(identity, plan_id)
    plan = next(item for item in workspace.plans if item.id == plan_id)
    store.audit(
        AuditEvent(
            conversation_id=plan.conversation_id,
            workspace_id=identity.workspace_id,
            actor="system",
            event_type="nous.plan.progressed",
            data={
                "plan_id": str(plan.id),
                "status": plan.status.value,
                "steps": [{"id": str(step.id), "status": step.status.value} for step in plan.steps],
            },
        )
    )
    return {"workspace": workspace.model_dump(mode="json")}


@app.post("/api/nous/plans/{plan_id}/external-actions", status_code=201)
async def create_nous_external_action(
    plan_id: UUID,
    request: CreateNousActionRequest,
    identity: Identity = Depends(require_identity),
) -> dict:
    ensure_feature(Product.NOUS)
    conversation = store.get_conversation(request.conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    current_workspace = nous_service.get_or_create_workspace(identity)
    current_plan = next((item for item in current_workspace.plans if item.id == plan_id), None)
    if not current_plan:
        raise HTTPException(status_code=404, detail="Plan not found")
    if current_plan.conversation_id != conversation.id:
        raise HTTPException(status_code=409, detail="Plan does not belong to this conversation")
    workspace, action, proposal = nous_service.create_external_action(identity, plan_id, request)
    plan = next(item for item in workspace.plans if item.id == plan_id)
    store.save_proposal(conversation.id, proposal)
    store.audit(
        AuditEvent(
            conversation_id=conversation.id,
            workspace_id=identity.workspace_id,
            actor="assistant",
            event_type="nous.external_action.proposed",
            data={
                "action_id": str(action.id),
                "kind": action.kind,
                "destination": action.destination,
                "proposal_id": str(proposal.id),
            },
        )
    )
    return {
        "workspace": workspace.model_dump(mode="json"),
        "action": action.model_dump(mode="json"),
        "proposal": proposal.model_dump(mode="json"),
    }


@app.get("/api/conversations/{conversation_id}/audit")
async def get_audit(
    conversation_id: UUID, identity: Identity = Depends(require_identity)
) -> dict:
    conversation = store.get_conversation(conversation_id)
    if not conversation:
        raise HTTPException(status_code=404, detail="Conversation not found")
    require_conversation_access(identity, conversation.workspace_id, conversation.owner_user_id)
    events = store.get_audit_events(conversation_id)
    return {"events": [event.model_dump(mode="json") for event in events]}
