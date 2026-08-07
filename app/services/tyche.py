from __future__ import annotations

import re
from collections import Counter
from datetime import datetime, timezone
from uuid import UUID

from fastapi import HTTPException

from app.domain.models import (
    ATSAnalysis,
    ATSDiagnostic,
    ContextSnapshot,
    EvidenceReference,
    JobDescription,
    Proposal,
    ResourceReference,
    ResumeBullet,
    ResumeBlock,
    ResumeDocument,
    SaveJobDescriptionRequest,
    TycheChange,
    TycheEvidenceItem,
    TycheWorkspace,
)
from app.services.auth import Identity
from app.services.resume_documents import ImportedDocument
from app.services.store import Store


SKILL_TERMS = (
    "product strategy",
    "product roadmap",
    "roadmap",
    "prioritisation",
    "prioritization",
    "stakeholder management",
    "customer research",
    "user research",
    "data analysis",
    "analytics",
    "experimentation",
    "a/b testing",
    "go-to-market",
    "agile",
    "sql",
    "leadership",
    "engineering",
    "design",
    "sales",
)
STOP_WORDS = {
    "about", "after", "also", "and", "are", "from", "have", "into", "our", "that",
    "the", "their", "this", "through", "with", "will", "you", "your", "role", "team",
    "work", "years", "looking", "responsible", "candidate", "experience",
}
ACTION_VERBS = {"led", "managed", "owned", "delivered", "launched", "increased", "reduced", "built", "drove"}


class TycheService:
    def __init__(self, store: Store) -> None:
        self.store = store

    def get_or_create_workspace(self, identity: Identity) -> TycheWorkspace:
        existing = self.store.get_tyche_workspace(identity.workspace_id, identity.user_id)
        if existing:
            return existing
        resume = ResumeDocument(
            id="resume-1",
            title="Product résumé",
            target_role="Senior Product Manager",
            company="Northstar Labs",
            role="Product Manager",
            period="2022–Present",
            bullets=[
                ResumeBullet(id="bullet-1", text="Managed the product roadmap."),
                ResumeBullet(
                    id="bullet-2",
                    text="Worked with engineering and design on product launches.",
                ),
            ],
        )
        workspace = TycheWorkspace(
            workspace_id=identity.workspace_id,
            owner_user_id=identity.user_id,
            resume=resume,
        )
        self._refresh(workspace)
        self.store.save_tyche_workspace(workspace)
        return workspace

    def save_job_description(
        self, identity: Identity, request: SaveJobDescriptionRequest
    ) -> TycheWorkspace:
        workspace = self.get_or_create_workspace(identity)
        keywords = self.extract_keywords(request.text)
        workspace.job_description = JobDescription(
            title=request.title,
            company=request.company,
            text=request.text,
            keywords=keywords,
        )
        workspace.resume.target_role = request.title
        self._refresh(workspace)
        self.store.save_tyche_workspace(workspace)
        return workspace

    def import_resume(
        self, identity: Identity, imported: ImportedDocument
    ) -> TycheWorkspace:
        workspace = self.get_or_create_workspace(identity)
        bullets = [
            ResumeBullet(id=block.id, text=block.text)
            for block in imported.blocks
            if block.kind == "bullet"
        ]
        if not bullets:
            raise HTTPException(
                status_code=422,
                detail="The résumé needs at least one readable experience statement",
            )
        workspace.resume.title = imported.filename.rsplit(".", 1)[0].replace("_", " ").replace("-", " ").strip()
        workspace.resume.candidate_name = imported.candidate_name
        workspace.resume.source_filename = imported.filename
        workspace.resume.blocks = imported.blocks
        workspace.resume.bullets = bullets
        workspace.resume.version += 1
        workspace.changes = []
        self._refresh(workspace)
        self.store.save_tyche_workspace(workspace)
        return workspace

    def prepare_context(self, identity: Identity, context: ContextSnapshot) -> ContextSnapshot:
        if context.product.value != "tyche" or not context.filters.get("grounded_workspace"):
            return context
        workspace = self.get_or_create_workspace(identity)
        bullet_id = context.selection.ids[0] if context.selection and context.selection.ids else None
        bullet = next((item for item in workspace.resume.bullets if item.id == bullet_id), None)
        if not bullet:
            raise HTTPException(status_code=409, detail="The selected résumé text no longer exists")
        context.page.id = workspace.resume.id
        context.page.type = "resume"
        context.page.label = workspace.resume.title
        context.selection.excerpt = bullet.text
        context.snapshot_version = workspace.resume.source_version
        context.filters["ats"] = workspace.ats.model_dump(mode="json") if workspace.ats else None
        context.filters["target_role"] = (
            workspace.job_description.title if workspace.job_description else workspace.resume.target_role
        )
        context.authorised_resources = [
            ResourceReference.model_validate({
                "id": workspace.resume.id,
                "type": "resume",
                "label": workspace.resume.title,
            })
        ]
        if workspace.job_description:
            context.authorised_resources.append(
                ResourceReference.model_validate({
                    "id": str(workspace.job_description.id),
                    "type": "job_description",
                    "label": f"{workspace.job_description.title} at {workspace.job_description.company}",
                    "excerpt": workspace.job_description.text,
                })
            )
        context.evidence_items = [self._evidence_reference(item) for item in workspace.evidence]
        return context

    def apply_proposal(
        self, identity: Identity, proposal: Proposal, suggested_text: str
    ) -> tuple[TycheWorkspace, TycheChange]:
        workspace = self.get_or_create_workspace(identity)
        if proposal.source_version != workspace.resume.source_version:
            raise HTTPException(status_code=409, detail="The résumé changed; generate a fresh proposal")
        bullet_id = str(proposal.payload.get("selection_ids", [""])[0])
        bullet = next((item for item in workspace.resume.bullets if item.id == bullet_id), None)
        if not bullet:
            raise HTTPException(status_code=409, detail="The selected résumé text no longer exists")
        if not suggested_text.strip():
            raise HTTPException(status_code=422, detail="Suggested text cannot be empty")
        before = bullet.text
        version_before = workspace.resume.version
        bullet.text = suggested_text.strip()
        self._sync_block(workspace.resume.blocks, bullet.id, bullet.text)
        workspace.resume.version += 1
        change = TycheChange(
            bullet_id=bullet.id,
            before=before,
            after=bullet.text,
            version_before=version_before,
            version_after=workspace.resume.version,
        )
        workspace.changes.append(change)
        self._refresh(workspace)
        self.store.save_tyche_workspace(workspace)
        return workspace, change

    def undo_change(self, identity: Identity, change_id: UUID) -> TycheWorkspace:
        workspace = self.get_or_create_workspace(identity)
        change = next((item for item in workspace.changes if item.id == change_id), None)
        if not change or change.undone:
            raise HTTPException(status_code=404, detail="Undo operation not found")
        if workspace.resume.version != change.version_after:
            raise HTTPException(status_code=409, detail="The résumé changed after this edit and cannot be safely undone")
        bullet = next((item for item in workspace.resume.bullets if item.id == change.bullet_id), None)
        if not bullet or bullet.text != change.after:
            raise HTTPException(status_code=409, detail="The edited text no longer matches")
        bullet.text = change.before
        self._sync_block(workspace.resume.blocks, bullet.id, bullet.text)
        workspace.resume.version += 1
        change.undone = True
        self._refresh(workspace)
        self.store.save_tyche_workspace(workspace)
        return workspace

    @staticmethod
    def extract_keywords(text: str) -> list[str]:
        lowered = text.lower()
        found = [term for term in SKILL_TERMS if term in lowered]
        words = re.findall(r"[a-z][a-z+.-]{3,}", lowered)
        frequent = [
            word for word, _ in Counter(word for word in words if word not in STOP_WORDS).most_common(12)
        ]
        combined: list[str] = []
        for keyword in [*found, *frequent]:
            if keyword not in combined:
                combined.append(keyword)
        return combined[:16]

    def analyse(self, workspace: TycheWorkspace) -> ATSAnalysis | None:
        if not workspace.job_description:
            return None
        resume_text = " ".join(item.text for item in workspace.resume.bullets).lower()
        keywords = workspace.job_description.keywords
        matched = [keyword for keyword in keywords if keyword in resume_text]
        missing = [keyword for keyword in keywords if keyword not in resume_text]
        keyword_score = round(100 * len(matched) / max(1, len(keywords)))
        has_metric = bool(re.search(r"\b\d+(?:[.,]\d+)?%?\b", resume_text))
        verbs_used = sorted(verb for verb in ACTION_VERBS if verb in resume_text)
        impact_score = min(100, (45 if has_metric else 10) + min(55, len(verbs_used) * 20))
        lengths = [len(item.text.split()) for item in workspace.resume.bullets]
        clarity_score = round(100 * sum(8 <= length <= 30 for length in lengths) / max(1, len(lengths)))
        format_score = 100 if all(item.text.endswith((".", "!")) for item in workspace.resume.bullets) else 80
        overall = round(keyword_score * 0.55 + impact_score * 0.25 + clarity_score * 0.15 + format_score * 0.05)
        return ATSAnalysis(
            score=overall,
            matched_keywords=matched,
            missing_keywords=missing,
            diagnostics=[
                ATSDiagnostic(
                    category="keywords",
                    score=keyword_score,
                    summary=f"Matched {len(matched)} of {len(keywords)} role keywords.",
                    recommendations=[f"Address {item} only if supported by your experience." for item in missing[:3]],
                ),
                ATSDiagnostic(
                    category="impact",
                    score=impact_score,
                    summary="Impact is assessed from action verbs and user-supplied metrics.",
                    recommendations=[] if has_metric else ["Add a measurable result only when you can verify it."],
                ),
                ATSDiagnostic(
                    category="clarity",
                    score=clarity_score,
                    summary="Checks whether bullets are concise enough to scan.",
                ),
                ATSDiagnostic(
                    category="format",
                    score=format_score,
                    summary="Checks consistent bullet punctuation and structure.",
                ),
            ],
        )

    def _refresh(self, workspace: TycheWorkspace) -> None:
        evidence: list[TycheEvidenceItem] = []
        for bullet in workspace.resume.bullets:
            evidence_id = f"resume:{bullet.id}"
            bullet.evidence_ids = [evidence_id]
            evidence.append(
                TycheEvidenceItem(
                    id=evidence_id,
                    kind="user_claim",
                    label=f"Résumé bullet {bullet.id.removeprefix('bullet-')}",
                    source_id=bullet.id,
                    excerpt=bullet.text,
                )
            )
        if workspace.job_description:
            for index, keyword in enumerate(workspace.job_description.keywords):
                evidence.append(
                    TycheEvidenceItem(
                        id=f"job:{workspace.job_description.id}:keyword:{index}",
                        kind="job_requirement",
                        label=f"Role requirement: {keyword}",
                        source_id=str(workspace.job_description.id),
                        excerpt=keyword,
                    )
                )
        workspace.evidence = evidence
        workspace.ats = self.analyse(workspace)
        workspace.updated_at = datetime.now(timezone.utc)

    @staticmethod
    def _sync_block(blocks: list[ResumeBlock], bullet_id: str, text: str) -> None:
        block = next((item for item in blocks if item.id == bullet_id), None)
        if block:
            block.text = text

    @staticmethod
    def _evidence_reference(item: TycheEvidenceItem) -> EvidenceReference:
        return EvidenceReference(
            id=item.id,
            label=item.label,
            resource_type=item.kind,
            resource_id=item.source_id,
            href=f"#evidence-{item.id.replace(':', '-')}",
            excerpt=item.excerpt,
        )
