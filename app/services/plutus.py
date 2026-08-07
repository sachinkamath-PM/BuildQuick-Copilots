from __future__ import annotations

import statistics
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from uuid import uuid4

from fastapi import HTTPException

from app.domain.models import (
    CategoryChange,
    ContextSnapshot,
    CoverageGap,
    DateRange,
    DetectedSubscription,
    EvidenceReference,
    FamilyMember,
    FinancialAccount,
    FinancialImportSummary,
    FinancialGoal,
    FinancialTransaction,
    GoalScenario,
    GoalScenarioRequest,
    InsurancePolicy,
    PlutusAnalysis,
    PlutusWorkspace,
    Proposal,
    ResourceReference,
    TransactionAnomaly,
)
from app.services.auth import Identity
from app.services.store import Store


class PlutusService:
    period_start = date(2026, 4, 1)
    period_end = date(2026, 6, 30)
    previous_start = date(2026, 1, 1)
    previous_end = date(2026, 3, 31)
    scenario_as_of = date(2026, 8, 7)

    def __init__(self, store: Store) -> None:
        self.store = store

    def get_or_create_workspace(self, identity: Identity) -> PlutusWorkspace:
        existing = self.store.get_plutus_workspace(identity.workspace_id, identity.user_id)
        if existing:
            return existing
        members = [
            FamilyMember(id="member-sachin", name="Sachin", relationship="Self"),
            FamilyMember(id="member-partner", name="Partner", relationship="Spouse"),
        ]
        accounts = [
            FinancialAccount(id="account-bank", name="Family Bank", account_type="bank", owner="Family", balance=500_000, previous_balance=540_000),
            FinancialAccount(id="account-invest", name="Investment Portfolio", account_type="investment", owner="Family", balance=8_000_000, previous_balance=8_200_000),
            FinancialAccount(id="account-home", name="Primary Home", account_type="property", owner="Family", balance=7_500_000, previous_balance=7_500_000),
            FinancialAccount(id="account-loan", name="Home Loan", account_type="loan", owner="Family", balance=-1_800_000, previous_balance=-1_750_000),
        ]
        transactions = self._seed_transactions()
        policies = [
            InsurancePolicy(id="policy-term", policy_type="Term life", insured_member_id="member-sachin", cover_amount=10_000_000, nominee_member_ids=[]),
            InsurancePolicy(id="policy-health", policy_type="Family health", insured_member_id="member-sachin", cover_amount=2_000_000, nominee_member_ids=["member-partner"], data_complete=False),
        ]
        analysis = self.analyse(accounts, transactions, policies)
        workspace = PlutusWorkspace(
            workspace_id=identity.workspace_id,
            owner_user_id=identity.user_id,
            members=members,
            accounts=accounts,
            transactions=transactions,
            policies=policies,
            analysis=analysis,
        )
        self.store.save_plutus_workspace(workspace)
        return workspace

    def prepare_context(self, identity: Identity, context: ContextSnapshot) -> ContextSnapshot:
        if context.product.value != "plutus" or not context.filters.get("grounded_workspace"):
            return context
        workspace = self.get_or_create_workspace(identity)
        context.page.id = "family-dashboard"
        context.page.type = "financial_dashboard"
        context.page.label = "Family overview"
        context.snapshot_version = workspace.source_version
        context.date_range = DateRange(
            start=workspace.analysis.period_start,
            end=workspace.analysis.period_end,
        )
        context.filters["analysis"] = workspace.analysis.model_dump(mode="json")
        context.filters["goals"] = [goal.model_dump(mode="json") for goal in workspace.goals]
        context.authorised_resources = [
            ResourceReference(id="family-dashboard", type="financial_dashboard", label="Family overview")
        ]
        context.evidence_items = self._evidence(workspace)
        return context

    def replace_records(
        self,
        identity: Identity,
        accounts: list[FinancialAccount] | None,
        transactions: list[FinancialTransaction] | None,
        *,
        accounts_filename: str | None,
        transactions_filename: str | None,
        warnings: list[str],
    ) -> PlutusWorkspace:
        if accounts is None and transactions is None:
            raise HTTPException(status_code=422, detail="Choose an accounts or transactions CSV")
        workspace = self.get_or_create_workspace(identity)
        replacement_accounts = accounts if accounts is not None else workspace.accounts
        replacement_transactions = transactions if transactions is not None else workspace.transactions
        account_ids = {item.id for item in replacement_accounts}
        unknown = sorted({item.account_id for item in replacement_transactions if item.account_id not in account_ids})
        if unknown:
            raise HTTPException(
                status_code=422,
                detail=f"Transactions reference unknown account ids: {', '.join(unknown[:8])}",
            )
        currencies = {item.currency for item in replacement_accounts}
        if len(currencies) > 1:
            raise HTTPException(
                status_code=422,
                detail="All accounts must use one currency; currency conversion is not inferred",
            )

        analysis = self.analyse(replacement_accounts, replacement_transactions, workspace.policies)
        comparison_start = date.fromisoformat(analysis.previous_period_start)
        comparison_end = date.fromisoformat(analysis.period_end)
        outside = sum(
            not comparison_start <= date.fromisoformat(item.date) <= comparison_end
            for item in replacement_transactions
        )
        if outside:
            warnings.append(
                f"{outside} transaction(s) fall outside the two comparison quarters; they remain available for recurring-charge detection."
            )
        used_accounts = {item.account_id for item in replacement_transactions}
        unused = len(account_ids - used_accounts)
        if unused:
            warnings.append(f"{unused} account(s) have no imported transactions.")

        workspace.accounts = replacement_accounts
        workspace.transactions = replacement_transactions
        workspace.analysis = analysis
        workspace.data_source = "csv"
        workspace.last_import = FinancialImportSummary(
            accounts_filename=accounts_filename,
            transactions_filename=transactions_filename,
            account_rows=len(accounts) if accounts is not None else 0,
            transaction_rows=len(transactions) if transactions is not None else 0,
            warnings=warnings,
        )
        workspace.version += 1
        workspace.updated_at = datetime.now(timezone.utc)
        self.store.save_plutus_workspace(workspace)
        return workspace

    def scenario(
        self, identity: Identity, request: GoalScenarioRequest
    ) -> tuple[PlutusWorkspace, GoalScenario, Proposal]:
        workspace = self.get_or_create_workspace(identity)
        try:
            target_date = date.fromisoformat(request.target_date)
        except ValueError:
            raise HTTPException(status_code=422, detail="Target date must be YYYY-MM-DD") from None
        months = (target_date.year - self.scenario_as_of.year) * 12 + target_date.month - self.scenario_as_of.month
        if months < 1:
            raise HTTPException(status_code=422, detail="Target date must be in the future")
        years = months / 12
        adjusted_target = request.target_amount * (1 + request.annual_inflation_rate) ** years
        monthly_rate = request.annual_return_rate / 12
        future_current = request.current_amount * (1 + monthly_rate) ** months
        shortfall = max(0.0, adjusted_target - future_current)
        if monthly_rate == 0:
            required = shortfall / months
        else:
            factor = ((1 + monthly_rate) ** months - 1) / monthly_rate
            required = shortfall / factor
        scenario = GoalScenario(
            name=request.name,
            target_amount_today=round(request.target_amount, 2),
            inflation_adjusted_target=round(adjusted_target, 2),
            current_amount=round(request.current_amount, 2),
            months=months,
            required_monthly_contribution=round(required, 2),
            annual_return_rate=request.annual_return_rate,
            annual_inflation_rate=request.annual_inflation_rate,
            formula="FV target minus FV current savings, funded by an end-of-month annuity",
        )
        proposal = Proposal(
            kind="financial_goal_creation",
            title=f"Create goal: {request.name}",
            summary=(
                f"Target ₹{scenario.inflation_adjusted_target:,.0f} by {request.target_date}; "
                f"proposed monthly contribution ₹{scenario.required_monthly_contribution:,.0f}."
            ),
            payload={
                "plutus_managed": True,
                "scenario": scenario.model_dump(mode="json"),
                "target_date": request.target_date,
            },
            source_version=workspace.source_version,
        )
        return workspace, scenario, proposal

    def apply_goal(self, identity: Identity, proposal: Proposal) -> PlutusWorkspace:
        workspace = self.get_or_create_workspace(identity)
        if proposal.source_version != workspace.source_version:
            raise HTTPException(status_code=409, detail="Financial workspace changed; review a fresh scenario")
        raw = proposal.payload.get("scenario")
        if not isinstance(raw, dict):
            raise HTTPException(status_code=422, detail="Goal proposal is incomplete")
        scenario = GoalScenario.model_validate(raw)
        workspace.goals.append(
            FinancialGoal(
                name=scenario.name,
                target_amount=scenario.inflation_adjusted_target,
                current_amount=scenario.current_amount,
                target_date=str(proposal.payload["target_date"]),
                monthly_contribution=scenario.required_monthly_contribution,
            )
        )
        workspace.version += 1
        workspace.updated_at = datetime.now(timezone.utc)
        self.store.save_plutus_workspace(workspace)
        return workspace

    def analyse(
        self,
        accounts: list[FinancialAccount],
        transactions: list[FinancialTransaction],
        policies: list[InsurancePolicy],
    ) -> PlutusAnalysis:
        period_start, period_end, previous_start, previous_end = self._comparison_periods(transactions)
        current = [item for item in transactions if period_start <= date.fromisoformat(item.date) <= period_end]
        previous = [item for item in transactions if previous_start <= date.fromisoformat(item.date) <= previous_end]
        current_by_category = self._sum_by_category(current)
        previous_by_category = self._sum_by_category(previous)
        categories = sorted(set(current_by_category) | set(previous_by_category))
        category_changes = [
            CategoryChange(
                category=category,
                current_spend=round(current_by_category.get(category, 0), 2),
                previous_spend=round(previous_by_category.get(category, 0), 2),
                change=round(current_by_category.get(category, 0) - previous_by_category.get(category, 0), 2),
            )
            for category in categories
        ]
        net_worth = sum(item.balance for item in accounts)
        previous_net_worth = sum(item.previous_balance for item in accounts)
        current_spending = sum(item.amount for item in current)
        previous_spending = sum(item.amount for item in previous)
        return PlutusAnalysis(
            period_start=period_start.isoformat(),
            period_end=period_end.isoformat(),
            previous_period_start=previous_start.isoformat(),
            previous_period_end=previous_end.isoformat(),
            net_worth=round(net_worth, 2),
            previous_net_worth=round(previous_net_worth, 2),
            net_worth_change=round(net_worth - previous_net_worth, 2),
            current_spending=round(current_spending, 2),
            previous_spending=round(previous_spending, 2),
            spending_change=round(current_spending - previous_spending, 2),
            category_changes=category_changes,
            subscriptions=self._subscriptions(transactions),
            anomalies=self._anomalies(current),
            coverage_gaps=self._coverage_gaps(policies),
        )

    @classmethod
    def _comparison_periods(
        cls, transactions: list[FinancialTransaction]
    ) -> tuple[date, date, date, date]:
        if not transactions:
            return cls.period_start, cls.period_end, cls.previous_start, cls.previous_end
        latest = max(date.fromisoformat(item.date) for item in transactions)
        quarter_month = ((latest.month - 1) // 3) * 3 + 1
        period_start = date(latest.year, quarter_month, 1)
        if quarter_month == 10:
            next_quarter = date(latest.year + 1, 1, 1)
        else:
            next_quarter = date(latest.year, quarter_month + 3, 1)
        period_end = next_quarter - timedelta(days=1)
        previous_end = period_start - timedelta(days=1)
        previous_quarter_month = ((previous_end.month - 1) // 3) * 3 + 1
        previous_start = date(previous_end.year, previous_quarter_month, 1)
        return period_start, period_end, previous_start, previous_end

    @staticmethod
    def _sum_by_category(items: list[FinancialTransaction]) -> dict[str, float]:
        totals: dict[str, float] = defaultdict(float)
        for item in items:
            totals[item.category] += item.amount
        return totals

    @staticmethod
    def _subscriptions(items: list[FinancialTransaction]) -> list[DetectedSubscription]:
        by_merchant: dict[str, list[FinancialTransaction]] = defaultdict(list)
        for item in items:
            by_merchant[item.merchant].append(item)
        subscriptions = []
        for merchant, transactions in by_merchant.items():
            amounts = [item.amount for item in transactions]
            if len(transactions) >= 3 and max(amounts) - min(amounts) <= max(amounts) * 0.1:
                ordered = sorted(transactions, key=lambda item: item.date)
                subscriptions.append(
                    DetectedSubscription(
                        merchant=merchant,
                        typical_amount=round(statistics.median(amounts), 2),
                        occurrences=len(transactions),
                        last_date=ordered[-1].date,
                        transaction_ids=[item.id for item in ordered],
                    )
                )
        return sorted(subscriptions, key=lambda item: item.typical_amount, reverse=True)

    @staticmethod
    def _anomalies(items: list[FinancialTransaction]) -> list[TransactionAnomaly]:
        by_category: dict[str, list[float]] = defaultdict(list)
        for item in items:
            by_category[item.category].append(item.amount)
        anomalies = []
        for item in items:
            baseline = statistics.median(by_category[item.category])
            if item.amount >= 10_000 and item.amount > baseline * 2.5:
                anomalies.append(
                    TransactionAnomaly(
                        transaction_id=item.id,
                        merchant=item.merchant,
                        category=item.category,
                        amount=item.amount,
                        reason=f"₹{item.amount:,.0f} is more than 2.5× the {item.category} median of ₹{baseline:,.0f}.",
                    )
                )
        return anomalies

    @staticmethod
    def _coverage_gaps(policies: list[InsurancePolicy]) -> list[CoverageGap]:
        gaps = []
        for policy in policies:
            if not policy.data_complete:
                gaps.append(CoverageGap(kind="insurance_data", status="data_incomplete", label=f"{policy.policy_type} policy details are incomplete.", source_id=policy.id))
            if policy.data_complete and not policy.nominee_member_ids:
                gaps.append(CoverageGap(kind="nominee", status="confirmed_missing", label=f"No nominee is recorded for {policy.policy_type}.", source_id=policy.id))
        return gaps

    @staticmethod
    def _evidence(workspace: PlutusWorkspace) -> list[EvidenceReference]:
        evidence = [
            EvidenceReference(
                id=f"account:{account.id}",
                label=account.name,
                resource_type="recorded_account",
                resource_id=account.id,
                href=f"#account-{account.id}",
                excerpt=f"Current ₹{account.balance:,.0f}; previous ₹{account.previous_balance:,.0f}",
            )
            for account in workspace.accounts
        ]
        evidence.extend(
            EvidenceReference(
                id=f"transaction:{item.id}",
                label=item.merchant,
                resource_type="recorded_transaction",
                resource_id=item.id,
                href=f"#transaction-{item.id}",
                excerpt=f"{item.date}: ₹{item.amount:,.0f} · {item.category}",
            )
            for item in workspace.transactions
        )
        evidence.extend(
            EvidenceReference(
                id=f"policy:{policy.id}",
                label=policy.policy_type,
                resource_type="recorded_policy",
                resource_id=policy.id,
                href=f"#policy-{policy.id}",
                excerpt=(
                    f"Cover ₹{policy.cover_amount:,.0f}; nominees {len(policy.nominee_member_ids)}; "
                    f"data {'complete' if policy.data_complete else 'incomplete'}"
                ),
            )
            for policy in workspace.policies
        )
        evidence.append(
            EvidenceReference(
                id="calculation:period-analysis",
                label="Period analysis calculation",
                resource_type="calculation",
                resource_id=workspace.analysis.calculation_version,
                href="#plutus-analysis",
                excerpt=(
                    f"Net worth change ₹{workspace.analysis.net_worth_change:,.0f}; "
                    f"spending change ₹{workspace.analysis.spending_change:,.0f}"
                ),
            )
        )
        return evidence

    @staticmethod
    def _seed_transactions() -> list[FinancialTransaction]:
        raw = [
            ("tx-nf-jan", "2026-01-05", "Netflix", "Subscriptions", 649),
            ("tx-nf-feb", "2026-02-05", "Netflix", "Subscriptions", 649),
            ("tx-nf-mar", "2026-03-05", "Netflix", "Subscriptions", 649),
            ("tx-nf-apr", "2026-04-05", "Netflix", "Subscriptions", 649),
            ("tx-nf-may", "2026-05-05", "Netflix", "Subscriptions", 649),
            ("tx-nf-jun", "2026-06-05", "Netflix", "Subscriptions", 649),
            ("tx-ad-jan", "2026-01-10", "Adobe", "Subscriptions", 1675),
            ("tx-ad-feb", "2026-02-10", "Adobe", "Subscriptions", 1675),
            ("tx-ad-mar", "2026-03-10", "Adobe", "Subscriptions", 1675),
            ("tx-ad-apr", "2026-04-10", "Adobe", "Subscriptions", 1675),
            ("tx-ad-may", "2026-05-10", "Adobe", "Subscriptions", 1675),
            ("tx-ad-jun", "2026-06-10", "Adobe", "Subscriptions", 1675),
            ("tx-gr-jan", "2026-01-14", "Fresh Basket", "Groceries", 8200),
            ("tx-gr-feb", "2026-02-14", "Fresh Basket", "Groceries", 8600),
            ("tx-gr-mar", "2026-03-14", "Fresh Basket", "Groceries", 8400),
            ("tx-gr-apr", "2026-04-14", "Fresh Basket", "Groceries", 9100),
            ("tx-gr-may", "2026-05-14", "Fresh Basket", "Groceries", 9400),
            ("tx-gr-jun", "2026-06-14", "Fresh Basket", "Groceries", 9200),
            ("tx-tr-apr", "2026-04-18", "Metro Rail", "Travel", 1800),
            ("tx-tr-may", "2026-05-18", "Metro Rail", "Travel", 2100),
            ("tx-tr-jun", "2026-06-20", "International Air", "Travel", 85_000),
            ("tx-dn-jan", "2026-01-22", "Local Dining", "Dining", 4500),
            ("tx-dn-feb", "2026-02-22", "Local Dining", "Dining", 5200),
            ("tx-dn-mar", "2026-03-22", "Local Dining", "Dining", 4800),
            ("tx-dn-apr", "2026-04-22", "Local Dining", "Dining", 6200),
            ("tx-dn-may", "2026-05-22", "Local Dining", "Dining", 6800),
            ("tx-dn-jun", "2026-06-22", "Local Dining", "Dining", 6100),
        ]
        return [
            FinancialTransaction(id=item_id, account_id="account-bank", date=tx_date, merchant=merchant, category=category, amount=amount)
            for item_id, tx_date, merchant, category, amount in raw
        ]
