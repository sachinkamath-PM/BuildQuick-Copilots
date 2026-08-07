from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from app.domain.models import (
    ContextSnapshot,
    CreateNousActionRequest,
    NousAgent,
    NousExternalAction,
    NousOutput,
    NousPlan,
    NousPlanStatus,
    NousPlanStep,
    NousSource,
    NousStepStatus,
    NousWorkspace,
    Proposal,
    ResourceReference,
)
from app.services.auth import Identity
from app.services.store import Store


class NousService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get_or_create_workspace(self, identity: Identity) -> NousWorkspace:
        existing = self.store.get_nous_workspace(identity.workspace_id, identity.user_id)
        if existing:
            return existing
        workspace = NousWorkspace(
            workspace_id=identity.workspace_id,
            owner_user_id=identity.user_id,
            agents=[
                NousAgent(id="agent-research", name="Research agent", role="Collects and validates authorised source material."),
                NousAgent(id="agent-analysis", name="Analysis agent", role="Clusters evidence and ranks opportunities."),
                NousAgent(id="agent-editor", name="Briefing agent", role="Turns findings into a reviewable decision brief."),
            ],
            sources=[
                NousSource(
                    id="source-feedback-q2",
                    label="Q2 customer feedback",
                    source_type="feedback_export",
                    content="12 requests for faster onboarding; 9 reports of unclear pricing; 7 requests for team permissions.",
                ),
                NousSource(
                    id="source-support-q2",
                    label="Q2 support themes",
                    source_type="support_summary",
                    content="Onboarding setup generated 31 tickets; billing questions generated 24; permissions generated 18.",
                ),
                NousSource(
                    id="source-nps-q2",
                    label="Q2 NPS notes",
                    source_type="research_notes",
                    content="Detractors most often cited setup time, pricing clarity, and lack of granular roles.",
                ),
            ],
        )
        self.store.save_nous_workspace(workspace)
        return workspace

    def add_sources(
        self, identity: Identity, sources: list[NousSource]
    ) -> NousWorkspace:
        workspace = self.get_or_create_workspace(identity)
        existing_ids = {source.id for source in workspace.sources}
        duplicate = next((source for source in sources if source.id in existing_ids), None)
        if duplicate:
            raise HTTPException(status_code=409, detail=f"{duplicate.filename or duplicate.label} is already imported")
        workspace.sources.extend(sources)
        workspace.version += 1
        self._save(workspace)
        return workspace

    def create_plan(
        self,
        identity: Identity,
        conversation_id: UUID,
        objective: str,
        source_ids: list[str] | None = None,
    ) -> tuple[NousWorkspace, NousPlan]:
        workspace = self.get_or_create_workspace(identity)
        available = {source.id: source for source in workspace.sources if source.authorised}
        selected_ids = list(dict.fromkeys(available.keys() if source_ids is None else source_ids))
        unknown = [source_id for source_id in selected_ids if source_id not in available]
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Unknown or unauthorised source ids: {', '.join(unknown[:8])}",
            )
        plan = NousPlan(
            conversation_id=conversation_id,
            objective=objective,
            source_ids=selected_ids,
            required_inputs=[] if selected_ids else ["At least one authorised source"],
            steps=[
                NousPlanStep(title="Validate the authorised feedback sources", agent_id="agent-research"),
                NousPlanStep(title="Cluster themes and rank opportunity evidence", agent_id="agent-analysis"),
                NousPlanStep(title="Prepare a three-priority review brief", agent_id="agent-editor"),
            ],
        )
        workspace.plans.append(plan)
        workspace.version += 1
        self._save(workspace)
        return workspace, plan

    def start_plan(self, identity: Identity, plan_id: UUID) -> NousWorkspace:
        workspace, plan = self._plan(identity, plan_id)
        if plan.status != NousPlanStatus.DRAFT:
            raise HTTPException(status_code=409, detail="Only a draft plan can be started")
        if plan.required_inputs:
            raise HTTPException(status_code=409, detail="Required inputs are missing")
        available = {source.id for source in workspace.sources if source.authorised}
        if any(source_id not in available for source_id in plan.source_ids):
            raise HTTPException(status_code=409, detail="A selected source is no longer authorised")
        plan.status = NousPlanStatus.RUNNING
        plan.steps[0].status = NousStepStatus.RUNNING
        plan.updated_at = datetime.now(timezone.utc)
        workspace.version += 1
        self._save(workspace)
        return workspace

    def advance_plan(self, identity: Identity, plan_id: UUID) -> NousWorkspace:
        workspace, plan = self._plan(identity, plan_id)
        if plan.status != NousPlanStatus.RUNNING:
            raise HTTPException(status_code=409, detail="Plan is not running")
        current = next((step for step in plan.steps if step.status == NousStepStatus.RUNNING), None)
        if not current:
            raise HTTPException(status_code=409, detail="Plan has no running step")
        output = self._produce_output(workspace, plan, current)
        workspace.outputs.append(output)
        current.output_id = output.id
        current.status = NousStepStatus.COMPLETED
        next_step = next((step for step in plan.steps if step.status == NousStepStatus.PENDING), None)
        if next_step:
            next_step.status = NousStepStatus.RUNNING
        else:
            plan.status = NousPlanStatus.REVIEWABLE
        plan.updated_at = datetime.now(timezone.utc)
        workspace.version += 1
        self._save(workspace)
        return workspace

    def create_external_action(
        self,
        identity: Identity,
        plan_id: UUID,
        request: CreateNousActionRequest,
    ) -> tuple[NousWorkspace, NousExternalAction, Proposal]:
        workspace, plan = self._plan(identity, plan_id)
        if plan.status != NousPlanStatus.REVIEWABLE:
            raise HTTPException(status_code=409, detail="The plan must be reviewable before proposing an external action")
        final_output = next(
            (output for output in reversed(workspace.outputs) if output.plan_id == plan.id and output.agent_id == "agent-editor"),
            None,
        )
        if not final_output:
            raise HTTPException(status_code=409, detail="No reviewable brief is available")
        action = NousExternalAction(
            plan_id=plan.id,
            kind=request.kind,
            destination=request.destination,
            content_preview=final_output.content,
        )
        workspace.external_actions.append(action)
        workspace.version += 1
        self._save(workspace)
        proposal = Proposal(
            kind="nous_external_action",
            title=f"Approve {request.kind} to {request.destination}",
            summary="Review the exact destination and content preview before approval.",
            payload={
                "nous_managed": True,
                "action_id": str(action.id),
                "plan_id": str(plan.id),
                "destination": action.destination,
                "content_preview": action.content_preview,
            },
            source_version=workspace.source_version,
        )
        return workspace, action, proposal

    def apply_external_action(self, identity: Identity, proposal: Proposal) -> NousWorkspace:
        workspace = self.get_or_create_workspace(identity)
        if proposal.source_version != workspace.source_version:
            raise HTTPException(status_code=409, detail="The plan changed; review a fresh action preview")
        try:
            action_id = UUID(str(proposal.payload["action_id"]))
            plan_id = UUID(str(proposal.payload["plan_id"]))
        except (KeyError, ValueError):
            raise HTTPException(status_code=422, detail="External action proposal is incomplete") from None
        action = next((item for item in workspace.external_actions if item.id == action_id), None)
        plan = next((item for item in workspace.plans if item.id == plan_id), None)
        if not action or not plan or action.status != "proposed":
            raise HTTPException(status_code=409, detail="External action is no longer actionable")
        # No connector is configured in this MVP. Approval is recorded, but nothing is sent or published.
        action.status = "approved"
        plan.status = NousPlanStatus.COMPLETED
        plan.updated_at = datetime.now(timezone.utc)
        workspace.version += 1
        self._save(workspace)
        return workspace

    def cancel_external_action(self, identity: Identity, proposal: Proposal) -> NousWorkspace:
        workspace = self.get_or_create_workspace(identity)
        action_id = proposal.payload.get("action_id")
        action = next((item for item in workspace.external_actions if str(item.id) == str(action_id)), None)
        if action and action.status == "proposed":
            action.status = "cancelled"
            workspace.version += 1
            self._save(workspace)
        return workspace

    def prepare_context(self, identity: Identity, context: ContextSnapshot) -> ContextSnapshot:
        if context.product.value != "nous" or not context.filters.get("grounded_workspace"):
            return context
        workspace = self.get_or_create_workspace(identity)
        context.page.id = "agent-workspace"
        context.page.type = "agent_workspace"
        context.page.label = "Agent workspace"
        context.snapshot_version = workspace.source_version
        context.filters["agents"] = [agent.model_dump(mode="json") for agent in workspace.agents]
        context.filters["active_plans"] = [plan.model_dump(mode="json") for plan in workspace.plans[-5:]]
        context.authorised_resources = [
            ResourceReference(id=source.id, type=source.source_type, label=source.label, excerpt=source.content)
            for source in workspace.sources if source.authorised
        ]
        return context

    def _plan(self, identity: Identity, plan_id: UUID) -> tuple[NousWorkspace, NousPlan]:
        workspace = self.get_or_create_workspace(identity)
        plan = next((item for item in workspace.plans if item.id == plan_id), None)
        if not plan:
            raise HTTPException(status_code=404, detail="Plan not found")
        return workspace, plan

    def _produce_output(self, workspace: NousWorkspace, plan: NousPlan, step: NousPlanStep) -> NousOutput:
        sources_by_id = {source.id: source for source in workspace.sources if source.authorised}
        sources = [sources_by_id[source_id] for source_id in plan.source_ids if source_id in sources_by_id]
        source_ids = [source.id for source in sources]
        themes = self._rank_themes(sources)
        if step.agent_id == "agent-research":
            labels = ", ".join(source.label for source in sources)
            record_count = sum(source.record_count for source in sources)
            content = f"Validated {len(sources)} authorised source(s) containing {record_count} record(s): {labels}."
            title = "Validated source inventory"
        elif step.agent_id == "agent-analysis":
            ranking = "; ".join(
                f"{index}) {theme} — {count} evidence mention(s)"
                for index, (theme, count) in enumerate(themes, start=1)
            )
            content = f"Evidence ranking: {ranking}."
            title = "Ranked opportunity evidence"
        else:
            recommendations = "\n".join(
                f"{index}. Investigate {theme} — supported by {count} evidence mention(s)."
                for index, (theme, count) in enumerate(themes, start=1)
            )
            content = (
                f"Recommended priorities:\n{recommendations}\n\n"
                "Review the underlying source excerpts and validate these themes with accountable owners before committing action."
            )
            title = "Three-priority customer opportunity brief"
        return NousOutput(
            plan_id=plan.id,
            step_id=step.id,
            agent_id=step.agent_id,
            title=title,
            content=content,
            source_ids=source_ids,
        )

    @staticmethod
    def _rank_themes(sources: list[NousSource]) -> list[tuple[str, int]]:
        combined = "\n".join(source.content.lower() for source in sources)
        known = {
            "onboarding": ("onboarding", "setup", "activation"),
            "pricing clarity": ("pricing", "billing", "price"),
            "team permissions": ("permission", "roles", "access control"),
            "performance": ("performance", "slow", "latency", "speed"),
            "integrations": ("integration", "api", "connector"),
            "reliability": ("reliability", "outage", "error", "failure"),
        }
        ranked = [
            (label, sum(len(re.findall(rf"\b{re.escape(term)}\w*\b", combined)) for term in terms))
            for label, terms in known.items()
        ]
        ranked = sorted((item for item in ranked if item[1]), key=lambda item: (-item[1], item[0]))
        if len(ranked) >= 3:
            return ranked[:3]
        stop_words = {
            "about", "after", "again", "also", "been", "customer", "customers", "data", "from",
            "have", "into", "more", "record", "source", "that", "their", "there", "they", "this",
            "with", "would", "your",
        }
        words = re.findall(r"[a-z][a-z-]{3,}", combined)
        for word, count in Counter(word for word in words if word not in stop_words).most_common(10):
            if word not in {item[0] for item in ranked}:
                ranked.append((word, count))
            if len(ranked) == 3:
                break
        while len(ranked) < 3:
            ranked.append(("additional evidence review", 0))
        return ranked[:3]

    def _save(self, workspace: NousWorkspace) -> None:
        workspace.updated_at = datetime.now(timezone.utc)
        self.store.save_nous_workspace(workspace)
