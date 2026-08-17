# BuildQuick Copilots

BuildQuick Copilots is a shared contextual-assistant laboratory for Tyche, Plutus, and Nous. It demonstrates how a product copilot can use explicit user context, cite authorised evidence, stream an explanation, propose a change, and wait for human approval before anything is applied.

The repository combines a FastAPI service, a responsive product workspace, durable storage, product-specific domain workflows, authentication adapters, audit events, and deployment hardening. It complements the product-owned applications; it is not their production runtime.

## Why this exists

Many assistants can answer a prompt but cannot show exactly what context they used, prove where a claim came from, or safely change a product record. This lab focuses on those trust and control problems.

Across all three products, the runtime:

- isolates workspaces by authenticated identity;
- makes the active product and selected records explicit;
- limits evidence to an authorised source catalogue;
- streams contextual responses;
- separates explanations from proposed mutations;
- checks source versions before applying a proposal;
- records request IDs, provider metadata, and audit events;
- supports conversation deletion and guest-data expiry;
- fails closed when production security settings are unsafe.

## Product experiences

### Tyche: evidence-grounded career editing

Tyche imports DOCX, PDF, or UTF-8 TXT resumes and a target job description. It preserves resume blocks, extracts claims as evidence, produces an explainable deterministic ATS analysis, and lets the copilot attach supported evidence to rewrite proposals.

Typical workflow:

1. Import a resume or use the demo resume.
2. Paste or import a job description and run **Analyse role**.
3. Review category scores and the evidence inventory.
4. Ask about the ATS result or request a rewrite of a selected claim.
5. Check the cited evidence and proposed diff.
6. Edit, apply, or cancel the proposal; use bounded undo if needed.
7. Export the current resume as a normalised DOCX.

The ATS score is a transparent product heuristic, not a prediction of an employer's proprietary screening system. Image-only PDFs require a future OCR adapter.

### Plutus: explainable family-finance analysis

Plutus stores family accounts, transactions, policies, and goals. It supports atomic CSV onboarding, quarter comparisons, subscription and unusual-transaction detection, nominee and insurance-data gap classification, and deterministic goal scenarios.

Typical workflow:

1. Switch to Plutus and open **Import records**.
2. Download the CSV templates or upload account and transaction files.
3. Review the validated workspace; when both files are supplied, they are committed as one atomic change.
4. Ask why net worth or spending changed and inspect evidence-linked calculations.
5. Create a goal scenario and review its assumptions.
6. Apply the scenario only after explicit approval.

Plutus supports INR records in this release and never initiates payments, investments, or live account connections. Explanations distinguish recorded facts, calculations, assumptions, and general guidance.

### Nous: multi-agent planning with locked provenance

Nous converts an outcome into an explicit multi-agent plan. Local TXT, CSV, and JSON files can be imported, selected for the next plan, and locked as its evidence set.

Typical workflow:

1. Import up to five local source files.
2. Select the exact sources the next plan may use.
3. Enter the desired outcome in **Ask Nous**.
4. Review required inputs, assigned agents, steps, and locked provenance.
5. Start the plan and advance its step states.
6. Inspect the source-attributed final brief.
7. Preview a proposed publish, send, or edit action.
8. Apply to record approval.

The MVP has no external publishing connector. Approval is audited, but no message, file, or post is actually sent.

## Assistant providers

The default provider is deterministic and requires no external service. This is the safest way to run the complete product workflows locally.

An OpenAI Responses API adapter is available behind configuration. It validates strict structured output, filters citations against the authorised evidence catalogue, hashes end-user identifiers, and never applies a model-proposed change directly.

## Run locally

### Requirements

- Python 3.11 or newer
- `pip`

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --require-hashes -r requirements.lock
python -m uvicorn app.main:app --reload
```

Open <http://127.0.0.1:8000>. Local defaults use SQLite, signed short-lived development identity, and the deterministic assistant.

To run tests in the same environment:

```bash
python -m pip install "pytest>=9,<10"
python -m pytest
```

## Configuration

Copy `.env.example` to a local ignored environment file or load the values through your normal secret manager. Never commit real secrets.

Important settings:

| Variable | Purpose | Local default |
| --- | --- | --- |
| `APP_ENV` | Selects development, demo, or production safeguards | `development` |
| `APP_SECRET` | Signs local or guest identity tokens | Placeholder; replace outside local use |
| `AUTH_MODE` | `local`, `guest`, or identity-provider `introspection` | `local` |
| `DATABASE_URL` | SQLite or PostgreSQL connection | `sqlite:///work/copilots.db` |
| `ASSISTANT_PROVIDER` | Deterministic `mock` or `openai` | `mock` |
| `FEATURE_TYCHE` | Enables the Tyche domain surface | `true` |
| `FEATURE_PLUTUS` | Enables the Plutus domain surface | `true` |
| `FEATURE_NOUS` | Enables the Nous domain surface | `true` |
| `REQUEST_LIMIT_PER_MINUTE` | Per-client API rate limit | `180` |
| `GUEST_RETENTION_HOURS` | Guest workspace lifetime | `24` |
| `ALLOWED_HOSTS` | Accepted request hosts | Localhost only |

Selecting `ASSISTANT_PROVIDER=openai` also requires `OPENAI_API_KEY`. Production should use PostgreSQL, `AUTH_MODE=introspection`, a strong unique secret, an explicit host allowlist, and HTTPS.

## Architecture

```text
Browser workspace
      |
      v
FastAPI routes and streaming responses
      |
      +-- identity and workspace isolation
      +-- product feature gates
      +-- authorised evidence catalogue
      +-- deterministic or OpenAI assistant provider
      +-- proposal/version checks and audit events
      |
      v
SQLite for local use / PostgreSQL for deployment
```

Repository layout:

```text
app/main.py                    HTTP routes, streaming, and product APIs
app/domain/                    Shared conversation and proposal models
app/services/assistant.py      Provider boundary and response validation
app/services/auth.py           Local, guest, and introspection identity
app/services/store.py          SQLite/PostgreSQL persistence
app/services/tyche.py          Resume evidence, ATS, proposal, and undo logic
app/services/plutus.py         Finance explanations and scenarios
app/services/nous.py           Sources, plans, steps, briefs, and actions
app/services/*_imports.py      Safe document, source, and CSV ingestion
app/static/                    Responsive browser workspace
tests/                         API, product, auth, and hardening coverage
docs/DEPLOYMENT.md             Public-demo and production deployment guide
```

Key API groups include health and readiness, identity tokens, conversations and streamed messages, proposal decisions, product workspaces, Tyche imports and export, Plutus imports and scenarios, Nous sources and plans, external-action previews, and conversation audit history. FastAPI's generated schema is available at `/docs` during local development.

## Data, safety, and retention

- Local data is written to `work/copilots.db` by default.
- `DATABASE_URL=postgresql://...` selects PostgreSQL.
- Uploads are size-bounded and parsed locally by the application.
- Invalid atomic imports leave the previous workspace untouched.
- Citations are restricted to the current identity's authorised evidence.
- Applying a proposal requires an explicit decision and a current source version.
- Guest workspaces expire automatically according to the retention settings.
- Browser security headers, host filtering, request IDs, and rate limits are enabled.

The local development token route is disabled by production settings. Identity-provider introspection establishes identity; deployment policy must still enforce the intended workspace membership and access rules.

## Operations

```bash
python -m app.maintenance migrate
python -m app.maintenance readiness
python -m app.maintenance cleanup-guests
```

Use these commands to apply database migrations, verify deployment readiness, and remove expired guest data.

## Containers and deployment

The repository includes:

- a non-root, read-only production container;
- a PostgreSQL Compose stack with health checks and durable volume;
- bounded process, memory, and CPU settings;
- GitHub Actions tests, compile checks, image build, and high-severity scanning;
- tag-triggered GHCR publishing with provenance attestation where GitHub supports it.

Read [the deployment guide](docs/DEPLOYMENT.md) before exposing the service publicly. It covers the public-demo profile, reverse proxy and HTTPS, privacy and retention, production identity, container security, updates, and rollback.

## Test and release workflow

```bash
python -m compileall -q app
python -m pytest -q
docker build -t buildquick-copilots:local .
```

Pull requests and pushes to `main` run the Python and container validation jobs. Tags matching `v*` publish a versioned image to GitHub Container Registry.

Production dependencies are pinned and hash-verified in `requirements.lock`. Regenerate the lock deliberately after reviewing dependency updates:

```bash
pip-compile --generate-hashes --strip-extras --output-file requirements.lock pyproject.toml
```

## Current boundaries

- Product mutations are implemented inside this lab's own durable workspace, not the standalone Tyche, Plutus, or Nous applications.
- The deterministic provider is intended for trustworthy product-flow testing, not open-ended intelligence.
- Live web research, Slack or Drive retrieval, bank aggregation, OCR, and external publishing each require a separately authorised connector or service.
- The OpenAI adapter requires production privacy, retention, cost, abuse, and evaluation controls appropriate to the deployment.
- No model response bypasses proposal review or directly performs an external action.

## Security

Do not publish suspected vulnerabilities in a public issue. Follow [SECURITY.md](SECURITY.md) for reporting and deployment-boundary guidance.
