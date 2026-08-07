# Deployment guide

This repository is packaged as one lab application because Tyche, Plutus, and Nous share the same API, policy layer, identity boundary, storage abstraction, and browser client. Deploy it at `copilots.buildquick.co.in`; the product domains remain owned by their respective repositories.

## Public demo profile

The supplied Compose profile runs an isolated guest demo behind PostgreSQL. Each browser tab receives a signed guest identity and a separate workspace. The default 24-hour retention window applies to both the token and stored workspace. This is suitable for product evaluation, not for storing regulated or sensitive information.

Prerequisites on the deployment host:

- Docker Engine with the Compose plugin
- a reverse proxy such as Caddy or Nginx
- DNS access for `copilots.buildquick.co.in`
- outbound access to GitHub Container Registry only if you later publish images there

Clone the private repository and create an ignored deployment environment file:

```bash
git clone https://github.com/sachinkamath-PM/BuildQuick-Copilots.git
cd BuildQuick-Copilots
cp .env.example .env.deploy
```

Generate independent URL-safe secrets and set at least these values in `.env.deploy`:

```dotenv
APP_SECRET=replace-with-at-least-32-random-bytes
POSTGRES_PASSWORD=replace-with-a-url-safe-random-password
ALLOWED_HOSTS=copilots.buildquick.co.in,localhost,127.0.0.1
ASSISTANT_PROVIDER=mock
GUEST_RETENTION_HOURS=24
```

Avoid punctuation that needs URL encoding in `POSTGRES_PASSWORD`, because Compose constructs `DATABASE_URL` from it.

Start and verify the services:

```bash
docker compose --env-file .env.deploy run --rm app python -m app.maintenance migrate
docker compose --env-file .env.deploy up -d --build
docker compose ps
curl --fail http://127.0.0.1:8000/api/ready
```

The application binds only to loopback. Terminate TLS at the reverse proxy and forward `https://copilots.buildquick.co.in` to `http://127.0.0.1:8000`. For Caddy, the site block is:

```caddyfile
copilots.buildquick.co.in {
    reverse_proxy 127.0.0.1:8000
}
```

Create `A`/`AAAA` records for the domain before starting Caddy so it can obtain certificates. Redirect the `www` hostname to the preferred canonical hostname if desired.

## Privacy and retention

- Do not upload real financial records, résumés, or confidential research to a public demo.
- Extracted upload contents are stored in PostgreSQL; original files are not retained.
- Guest workspaces are isolated and expire after `GUEST_RETENTION_HOURS`. The application removes expired workspaces on the configured cleanup interval. `python -m app.maintenance cleanup-guests` is also available as an idempotent operational fallback.
- To erase all demo data, stop the stack and deliberately remove the `buildquick-copilots_postgres-data` volume. This is destructive and should only be done after backups are considered.
- Use an identity provider and formal retention process before allowing real customer data.

## Production identity profile

For a real authenticated deployment, use `APP_ENV=production`, `AUTH_MODE=introspection`, an HTTPS `IDENTITY_INTROSPECTION_URL`, PostgreSQL, explicit `ALLOWED_HOSTS`, and a strong `APP_SECRET`. The browser login flow must be integrated with the chosen identity provider before this profile can be used through the bundled UI.

Set `MIGRATE_ON_STARTUP=false` for a real authenticated deployment. Apply migrations as a separate release step with `python -m app.maintenance migrate`, then verify the database with `python -m app.maintenance readiness` before starting new application instances.

Set `ASSISTANT_PROVIDER=openai` only when `OPENAI_API_KEY` is supplied through the host's secret manager. The deterministic mock provider requires no external AI API.

## Container security gate

Pull requests fail when the production image contains an unexcepted high- or critical-severity vulnerability. The narrowly scoped exceptions in `.grype.yaml` apply only to Python 3.13.14 advisories without a stable fixed runtime. They remain visible in CI and must be reviewed by 31 October 2026, or earlier when a stable Python fix is released.

## Updating and rollback

Before an update, create an encrypted-at-rest host backup and verify that the output is non-empty:

```bash
./scripts/backup-postgres.sh .env.deploy
gzip --test backups/buildquick-copilots-*.sql.gz
```

Copy backups away from the application host according to the retention policy. Test restoration into a separate PostgreSQL database before relying on the procedure.

```bash
git fetch --tags origin
git checkout <release-tag>
docker compose --env-file .env.deploy up -d --build
```

Rollback by checking out the previous signed-off tag or selecting the previous immutable GHCR image and rebuilding. Back up PostgreSQL before deploying migrations or making destructive operational changes. A release tag publishes `ghcr.io/sachinkamath-pm/buildquick-copilots:<tag>`; deployment from that image remains an explicit operation on the authorised host.
