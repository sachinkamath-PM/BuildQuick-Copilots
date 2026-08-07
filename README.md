# BuildQuick Copilots — Tyche, Plutus and Nous lab

A working shared contextual-chat foundation for Tyche, Plutus, and Nous. It includes a responsive product workspace, collapsible assistant, streamed messages, explicit context, evidence links, reviewable proposals, source-version checks, durable storage, workspace isolation, and audit events.

Tyche now includes durable résumé and job-description records, safe DOCX/PDF/TXT imports, structure-preserving résumé blocks, a normalized DOCX export, a deterministic ATS analysis, a visible evidence inventory, server-grounded chat context, supported-claim links on rewrite proposals, conflict-safe Apply, and bounded Undo. Imported claims become explicit evidence items; accepted rewrites update both the editable claim and its exported document block. The ATS score is an explainable product heuristic—not a prediction of any employer's proprietary screening system.

Plutus now includes durable family accounts, transactions, policies and goals; atomic CSV onboarding for real account and expense records; automatically selected quarter comparisons; subscription and unusual-transaction detection; nominee and insurance-data gap classification; evidence-linked explanations; and deterministic goal scenarios. Invalid imports leave the prior workspace untouched. Goal scenarios remain unapplied proposals until the user explicitly selects Apply. Plutus does not execute payments or investments.

Nous now turns an outcome entered in chat into an explicit multi-agent plan. TXT, CSV, and JSON source files can be imported locally, selected per plan, and locked as that plan's evidence set. The workspace shows required inputs, assigned agents, live step states, source-attributed outputs, a reviewable final brief, and exact previews for proposed publish/send/edit actions. The deterministic local analysis ranks supported themes without a model API. The MVP records approval but has no external connector, so it never actually sends or publishes content.

The shared runtime now fails closed on unsafe production configuration, supports per-product rollout flags, adds request IDs and safe provider metadata to audit records, applies API rate limits and browser security headers, and lets users delete individual conversations. Local defaults continue to run without external credentials.

The repository includes a non-root Docker image, PostgreSQL Compose stack, GitHub Actions validation, explicit host filtering, automatic guest-data expiry, and an isolated guest-demo mode for deployment behind HTTPS. See [the deployment guide](docs/DEPLOYMENT.md) before exposing the application publicly. This lab complements the product-owned copilots; it is not the production runtime for Tyche, Plutus, or Nous.

The default assistant provider is deterministic and requires no external API. A production OpenAI Responses API adapter is included behind configuration, validates strict structured output, filters citations to the authorised evidence catalog, hashes end-user identifiers, and never applies model-proposed changes directly. Local development uses a signed short-lived demo identity; production disables the demo-token route and can use OAuth token introspection.

## Run

```bash
python3 -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. In Tyche, submit “Make this more senior” to exercise the full context → streaming response → evidence → diff → apply flow.

To exercise the complete Tyche flow:

1. Import a DOCX, PDF, or UTF-8 TXT résumé (8 MB maximum), or use the demo résumé.
2. Paste or import a target job description and select **Analyse role**.
3. Inspect the deterministic category scores and evidence inventory.
4. Ask “Why is my ATS score low?” or select a claim and ask “Make this more senior.”
5. Review supporting evidence, edit the proposed wording, then Apply or Undo.
6. Export the current reviewable résumé as a normalized DOCX.

For Plutus, switch products in the top navigation and select **Import records**. Download the templates or upload one or both CSV files; when both are supplied they are validated as one atomic change. Plutus requires stable account IDs, ISO dates, positive expense amounts, negative loan balances, and INR accounts in this release. It selects the calendar quarter containing the latest transaction and compares it with the preceding quarter. You can then ask why net worth or spending changed, inspect detected subscriptions and unusual transactions, or open **Plan a goal**. Every explanation separates recorded facts, calculations, assumptions and general guidance.

For Nous, import up to five TXT, CSV, or JSON sources at once, select the exact sources the next plan may use, then enter an outcome in Ask Nous. Review the generated plan and its locked provenance, start it, watch each agent step progress, inspect the source-attributed brief, and preview a publish action. Apply records approval only; it does not execute an external action.

Runtime data is stored in `work/copilots.db`. Copy `.env.example` into your secret-management system and configure environment variables there. In production, use PostgreSQL, `AUTH_MODE=introspection`, and `APP_ENV=production` to disable the demo token endpoint.

Operational commands:

```bash
python3 -m app.maintenance migrate
python3 -m app.maintenance readiness
python3 -m app.maintenance cleanup-guests
```

## Test

```bash
python3 -m pytest
```

Production container dependencies are pinned and hash-verified in `requirements.lock`. Regenerate it deliberately after reviewing dependency updates with `pip-compile --generate-hashes --strip-extras --output-file requirements.lock pyproject.toml`.

## Current boundaries

- Applying a proposal updates the demo workspace and durable audit trail; a real product adapter will perform the domain mutation.
- SQLite is the local default; `DATABASE_URL=postgresql://...` selects the PostgreSQL repository.
- Authentication uses signed local tokens by default; `AUTH_MODE=introspection` verifies access tokens with the configured identity provider.
- `ASSISTANT_PROVIDER=openai` selects the Responses API adapter and requires `OPENAI_API_KEY`.
- Tyche imports DOCX, PDF, and UTF-8 TXT locally. PDF extraction is text-based, so image-only scans require a future OCR adapter. DOCX export uses a normalized accessible layout rather than attempting pixel-perfect reproduction of the source file.
- Plutus CSV import runs locally and needs no bank-data provider. Live account syncing would require a separately authorised aggregation API; the current release deliberately supports INR-only, expense-only transaction imports and never initiates financial transactions.
- Nous source extraction and deterministic theme ranking run locally. Live web research, Slack/Drive retrieval, model-generated synthesis, or actual publishing would each require a separately authorised connector or API; none is silently invoked by the current release.
