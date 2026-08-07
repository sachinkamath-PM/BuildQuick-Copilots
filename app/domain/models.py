from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, Field


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Product(str, Enum):
    TYCHE = "tyche"
    PLUTUS = "plutus"
    NOUS = "nous"


class ResourceReference(BaseModel):
    id: str
    type: str
    label: str
    excerpt: str | None = None


class PageContext(BaseModel):
    type: str
    id: str | None = None
    label: str | None = None


class SelectionContext(BaseModel):
    type: str
    ids: list[str]
    label: str | None = None
    excerpt: str | None = None


class DateRange(BaseModel):
    start: str
    end: str


class EvidenceReference(BaseModel):
    id: str
    label: str
    resource_type: str
    resource_id: str
    href: str | None = None
    excerpt: str | None = None


class ContextSnapshot(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    product: Product
    page: PageContext
    selection: SelectionContext | None = None
    filters: dict[str, Any] = Field(default_factory=dict)
    date_range: DateRange | None = None
    authorised_resources: list[ResourceReference] = Field(default_factory=list)
    evidence_items: list[EvidenceReference] = Field(default_factory=list)
    snapshot_version: str = "1"
    workspace_id: str | None = None
    created_by: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class DiffBlock(BaseModel):
    original: str
    suggested: str


class ProposalStatus(str, Enum):
    DRAFT = "draft"
    PRESENTED = "presented"
    EDITED = "edited"
    APPROVED = "approved"
    CANCELLED = "cancelled"
    APPLIED = "applied"
    FAILED = "failed"


class Proposal(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    kind: str
    title: str
    summary: str
    diff: DiffBlock | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    status: ProposalStatus = ProposalStatus.PRESENTED
    source_version: str
    requires_confirmation: bool = True
    applied_idempotency_key: str | None = None
    created_at: datetime = Field(default_factory=utc_now)


class MessageRole(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class AssistantMessage(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    role: MessageRole
    content: str
    context_snapshot_id: UUID | None = None
    evidence: list[EvidenceReference] = Field(default_factory=list)
    proposals: list[Proposal] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class Conversation(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    product: Product
    workspace_id: str
    owner_user_id: str
    title: str = "New conversation"
    messages: list[AssistantMessage] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class AuditEvent(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    workspace_id: str
    actor: Literal["user", "assistant", "system"]
    event_type: str
    data: dict[str, Any] = Field(default_factory=dict)
    created_at: datetime = Field(default_factory=utc_now)


class CreateConversationRequest(BaseModel):
    product: Product


class SendMessageRequest(BaseModel):
    content: str = Field(min_length=1, max_length=10_000)
    context: ContextSnapshot


class UpdateProposalRequest(BaseModel):
    action: Literal["apply", "edit", "cancel"]
    suggested_text: str | None = None
    source_version: str


class ResumeBullet(BaseModel):
    id: str
    text: str = Field(min_length=1, max_length=2_000)
    evidence_ids: list[str] = Field(default_factory=list)


class ResumeBlock(BaseModel):
    id: str
    kind: Literal["heading", "paragraph", "bullet"]
    text: str = Field(min_length=1, max_length=2_000)
    level: int = Field(default=0, ge=0, le=3)


class ResumeDocument(BaseModel):
    id: str
    title: str
    target_role: str
    company: str
    role: str
    period: str
    bullets: list[ResumeBullet]
    candidate_name: str | None = Field(default=None, max_length=200)
    source_filename: str | None = Field(default=None, max_length=255)
    blocks: list[ResumeBlock] = Field(default_factory=list)
    version: int = 1

    @property
    def source_version(self) -> str:
        return f"{self.id}:v{self.version}"


class JobDescription(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=30, max_length=30_000)
    keywords: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)


class TycheEvidenceItem(BaseModel):
    id: str
    kind: Literal["user_claim", "job_requirement"]
    label: str
    source_id: str
    excerpt: str


class ATSDiagnostic(BaseModel):
    category: Literal["keywords", "impact", "clarity", "format"]
    score: int = Field(ge=0, le=100)
    summary: str
    recommendations: list[str] = Field(default_factory=list)


class ATSAnalysis(BaseModel):
    score: int = Field(ge=0, le=100)
    matched_keywords: list[str] = Field(default_factory=list)
    missing_keywords: list[str] = Field(default_factory=list)
    diagnostics: list[ATSDiagnostic] = Field(default_factory=list)
    deterministic: bool = True


class TycheChange(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    bullet_id: str
    before: str
    after: str
    version_before: int
    version_after: int
    undone: bool = False
    created_at: datetime = Field(default_factory=utc_now)


class TycheWorkspace(BaseModel):
    workspace_id: str
    owner_user_id: str
    resume: ResumeDocument
    job_description: JobDescription | None = None
    evidence: list[TycheEvidenceItem] = Field(default_factory=list)
    ats: ATSAnalysis | None = None
    changes: list[TycheChange] = Field(default_factory=list)
    updated_at: datetime = Field(default_factory=utc_now)


class SaveJobDescriptionRequest(BaseModel):
    title: str = Field(min_length=1, max_length=200)
    company: str = Field(min_length=1, max_length=200)
    text: str = Field(min_length=30, max_length=30_000)


class FinancialAccount(BaseModel):
    id: str
    name: str
    account_type: Literal["bank", "investment", "loan", "property"]
    owner: str
    balance: float
    previous_balance: float
    currency: str = "INR"


class FinancialTransaction(BaseModel):
    id: str
    account_id: str
    date: str
    merchant: str
    category: str
    amount: float = Field(gt=0)


class FamilyMember(BaseModel):
    id: str
    name: str
    relationship: str


class InsurancePolicy(BaseModel):
    id: str
    policy_type: str
    insured_member_id: str
    cover_amount: float
    nominee_member_ids: list[str] = Field(default_factory=list)
    data_complete: bool = True


class FinancialGoal(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    target_amount: float
    current_amount: float
    target_date: str
    monthly_contribution: float
    status: Literal["active", "completed"] = "active"
    created_at: datetime = Field(default_factory=utc_now)


class DetectedSubscription(BaseModel):
    merchant: str
    typical_amount: float
    occurrences: int
    last_date: str
    transaction_ids: list[str]


class TransactionAnomaly(BaseModel):
    transaction_id: str
    merchant: str
    category: str
    amount: float
    reason: str


class CoverageGap(BaseModel):
    kind: Literal["nominee", "insurance_data"]
    status: Literal["confirmed_missing", "data_incomplete"]
    label: str
    source_id: str


class CategoryChange(BaseModel):
    category: str
    current_spend: float
    previous_spend: float
    change: float


class PlutusAnalysis(BaseModel):
    period_start: str
    period_end: str
    previous_period_start: str
    previous_period_end: str
    net_worth: float
    previous_net_worth: float
    net_worth_change: float
    current_spending: float
    previous_spending: float
    spending_change: float
    category_changes: list[CategoryChange]
    subscriptions: list[DetectedSubscription]
    anomalies: list[TransactionAnomaly]
    coverage_gaps: list[CoverageGap]
    calculation_version: str = "plutus-analysis-v1"


class FinancialImportSummary(BaseModel):
    accounts_filename: str | None = None
    transactions_filename: str | None = None
    account_rows: int = Field(ge=0)
    transaction_rows: int = Field(ge=0)
    warnings: list[str] = Field(default_factory=list)
    imported_at: datetime = Field(default_factory=utc_now)


class PlutusWorkspace(BaseModel):
    workspace_id: str
    owner_user_id: str
    members: list[FamilyMember]
    accounts: list[FinancialAccount]
    transactions: list[FinancialTransaction]
    policies: list[InsurancePolicy]
    goals: list[FinancialGoal] = Field(default_factory=list)
    analysis: PlutusAnalysis
    data_source: Literal["demo", "csv"] = "demo"
    last_import: FinancialImportSummary | None = None
    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def source_version(self) -> str:
        return f"plutus:v{self.version}"


class GoalScenarioRequest(BaseModel):
    conversation_id: UUID
    name: str = Field(min_length=1, max_length=160)
    target_amount: float = Field(gt=0)
    current_amount: float = Field(ge=0)
    target_date: str
    annual_return_rate: float = Field(ge=-0.2, le=0.3)
    annual_inflation_rate: float = Field(ge=0, le=0.2)


class GoalScenario(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    name: str
    target_amount_today: float
    inflation_adjusted_target: float
    current_amount: float
    months: int
    required_monthly_contribution: float
    annual_return_rate: float
    annual_inflation_rate: float
    formula: str
    calculation_version: str = "goal-scenario-v1"


class NousAgent(BaseModel):
    id: str
    name: str
    role: str


class NousSource(BaseModel):
    id: str
    label: str
    source_type: str
    content: str
    authorised: bool = True
    filename: str | None = None
    record_count: int = Field(default=1, ge=0)
    byte_size: int = Field(default=0, ge=0)
    created_at: datetime = Field(default_factory=utc_now)


class NousStepStatus(str, Enum):
    PENDING = "pending"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class NousPlanStatus(str, Enum):
    DRAFT = "draft"
    RUNNING = "running"
    REVIEWABLE = "reviewable"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class NousPlanStep(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    title: str
    agent_id: str
    status: NousStepStatus = NousStepStatus.PENDING
    requires_approval: bool = False
    output_id: UUID | None = None


class NousPlan(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    conversation_id: UUID
    objective: str = Field(min_length=5, max_length=5_000)
    status: NousPlanStatus = NousPlanStatus.DRAFT
    steps: list[NousPlanStep]
    source_ids: list[str] = Field(default_factory=list)
    required_inputs: list[str] = Field(default_factory=list)
    created_at: datetime = Field(default_factory=utc_now)
    updated_at: datetime = Field(default_factory=utc_now)


class NousOutput(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    step_id: UUID
    agent_id: str
    title: str
    content: str
    source_ids: list[str]
    created_at: datetime = Field(default_factory=utc_now)


class NousExternalAction(BaseModel):
    id: UUID = Field(default_factory=uuid4)
    plan_id: UUID
    kind: Literal["publish", "send", "edit_system"]
    destination: str
    content_preview: str
    status: Literal["proposed", "approved", "cancelled"] = "proposed"
    created_at: datetime = Field(default_factory=utc_now)


class NousWorkspace(BaseModel):
    workspace_id: str
    owner_user_id: str
    agents: list[NousAgent]
    sources: list[NousSource]
    plans: list[NousPlan] = Field(default_factory=list)
    outputs: list[NousOutput] = Field(default_factory=list)
    external_actions: list[NousExternalAction] = Field(default_factory=list)
    version: int = 1
    updated_at: datetime = Field(default_factory=utc_now)

    @property
    def source_version(self) -> str:
        return f"nous:v{self.version}"


class CreateNousPlanRequest(BaseModel):
    conversation_id: UUID
    objective: str = Field(min_length=5, max_length=5_000)
    source_ids: list[str] | None = Field(default=None, max_length=50)


class CreateNousActionRequest(BaseModel):
    conversation_id: UUID
    kind: Literal["publish", "send", "edit_system"]
    destination: str = Field(min_length=2, max_length=500)
