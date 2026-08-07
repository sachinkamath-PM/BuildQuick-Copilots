# Deployment guide

BuildQuick Copilots is packaged as one lab application because Tyche, Plutus, and Nous share the same API, policy layer, identity boundary, storage abstraction, and browser client. The intended public-demo hostname is `copilots.buildquick.co.in`; the product domains remain owned by their respective repositories.

The current reviewed release is `v0.10.1`, published as `ghcr.io/sachinkamath-pm/buildquick-copilots:v0.10.1`.

## Choose an appropriate host

The supplied Compose stack is an isolated guest demo backed by PostgreSQL. Each browser receives a signed guest identity and separate workspace, and guest data expires after 24 hours by default. It is suitable for non-sensitive product evaluation only.

Use an always-on managed host or dedicated server for sustained public availability. Docker Desktop can run the demo locally, but publishing a workstation additionally requires:

- a stable public IP or managed tunnel hostname;
- router/NAT forwarding for TCP ports 80 and 443 when applicable;
- host-firewall rules that expose only the reverse proxy, not PostgreSQL or the application port;
- sleep disabled while the service is expected to remain available; and
- an HTTPS reverse proxy such as Caddy or Nginx.

Do not create the public DNS record until the host is reachable and the reverse proxy is ready.

## Prepare the host

Prerequisites:

- Docker Engine or Docker Desktop with the Compose plugin;
- a reverse proxy such as Caddy or Nginx;
- DNS access for `copilots.buildquick.co.in`; and
- access to GitHub Container Registry when the package is not public.

Clone the private repository and create the ignored environment file:

```bash
git clone https://github.com/sachinkamath-PM/BuildQuick-Copilots.git
cd BuildQuick-Copilots
cp .env.example .env.deploy
chmod 600 .env.deploy
```

Set at least these values in `.env.deploy`:

```dotenv
APP_SECRET=replace-with-at-least-32-random-bytes
POSTGRES_PASSWORD=replace-with-a-url-safe-random-password
POSTGRES_DB=copilots
POSTGRES_USER=copilots
ALLOWED_HOSTS=copilots.buildquick.co.in,localhost,127.0.0.1
ASSISTANT_PROVIDER=mock
GUEST_RETENTION_HOURS=24
IMAGE_TAG=v0.10.1
APP_PORT=8000
```

Generate independent random values for `APP_SECRET` and `POSTGRES_PASSWORD`. Avoid punctuation that needs URL encoding in `POSTGRES_PASSWORD`, because Compose constructs `DATABASE_URL` from it. Never commit `.env.deploy`.

If port 8000 is already occupied, set `APP_PORT=8001` and use that same port in the reverse-proxy configuration.

## Authenticate to GHCR when required

If `docker compose pull app` reports a permission error, create a GitHub token with `read:packages`, then log in without placing the token directly on the command line:

```bash
read -s GHCR_TOKEN
printf '%s' "$GHCR_TOKEN" | docker login ghcr.io --username sachinkamath-PM --password-stdin
unset GHCR_TOKEN
```

The repository may remain private while the public website is accessible. Registry credentials belong on the deployment host, not in the repository or `.env.deploy`.

## Deploy the reviewed image

Validate the resolved configuration, pull the selected release, start the stack without rebuilding it, and verify both containers:

```bash
docker compose --env-file .env.deploy config
docker compose --env-file .env.deploy pull app
docker compose --env-file .env.deploy up -d --no-build --wait
docker compose --env-file .env.deploy ps
docker compose --env-file .env.deploy exec -T app python -m app.maintenance readiness
```

The public-demo profile applies migrations automatically on startup. The application binds only to loopback at `127.0.0.1:${APP_PORT}`; PostgreSQL is not published to the host.

To build the current checkout for local development instead of using a release image:

```bash
IMAGE_TAG=local docker compose --env-file .env.deploy up -d --build --wait
```

## Configure HTTPS and DNS

Terminate TLS at the reverse proxy and forward the public hostname to the configured loopback port. With `APP_PORT=8000`, a Caddy site block is:

```caddyfile
copilots.buildquick.co.in {
    reverse_proxy 127.0.0.1:8000
}
```

Create an `A` record for `copilots` pointing to the host's stable public IPv4 address. Add an `AAAA` record only when the host has working public IPv6. When a managed hosting provider supplies a hostname instead of an IP address, create the provider-prescribed `CNAME` record instead.

For a workstation behind a router, forward public TCP ports 80 and 443 to the workstation before requesting a certificate. Confirm that HTTPS works from a network outside the local Wi-Fi before treating the demo as public.

## Privacy and retention

- Do not upload real financial records, résumés, or confidential research to a public demo.
- Extracted upload contents are stored in PostgreSQL; original files are not retained.
- Guest workspaces are isolated and expire after `GUEST_RETENTION_HOURS`. The application removes expired workspaces on the configured cleanup interval. `python -m app.maintenance cleanup-guests` is also available as an idempotent fallback.
- Use an identity provider and formal retention process before allowing real customer data.

## Production identity boundary

The bundled Compose file intentionally runs the guest-demo profile. A real authenticated deployment requires a deployment-specific override or orchestrator that supplies `APP_ENV=production`, `AUTH_MODE=introspection`, an HTTPS `IDENTITY_INTROSPECTION_URL`, PostgreSQL, explicit `ALLOWED_HOSTS`, and a strong `APP_SECRET`. The browser login flow must also be integrated with the chosen identity provider.

For that profile, set `MIGRATE_ON_STARTUP=false`, apply migrations as a separate release step, and verify readiness before starting new application instances. Set `ASSISTANT_PROVIDER=openai` only when `OPENAI_API_KEY` is supplied through the host's secret manager. The deterministic mock provider requires no external AI API.

## Backups and restore drills

Before an update, create a compressed, permission-restricted PostgreSQL dump:

```bash
./scripts/backup-postgres.sh .env.deploy
gzip --test backups/buildquick-copilots-*.sql.gz
```

Gzip compression is not encryption. Store backups on encrypted-at-rest host storage, copy them to a separately protected location, and apply an explicit retention policy.

Test restoration into a separate disposable PostgreSQL database or isolated Compose project. Do not test by overwriting the active demo database. A backup is not considered reliable until a restore drill completes successfully.

## Updates and rollback

Before updating, back up PostgreSQL. Change `IMAGE_TAG` in `.env.deploy` to the reviewed release, then run:

```bash
docker compose --env-file .env.deploy pull app
docker compose --env-file .env.deploy up -d --no-build --wait
docker compose --env-file .env.deploy exec -T app python -m app.maintenance readiness
```

Rollback uses the same procedure with the previous release tag. Do not use a floating `latest` tag. Release tags publish both `ghcr.io/sachinkamath-pm/buildquick-copilots:<tag>` and a commit-SHA tag.

## Security gate

Pull requests fail when the production image contains an unexcepted high- or critical-severity vulnerability. The narrowly scoped exceptions in `.grype.yaml` apply only to Python 3.13.14 advisories without a stable fixed runtime. They remain visible in CI and must be reviewed by 31 October 2026, or earlier when a stable Python fix is released.

GitHub provenance attestation runs when the repository visibility supports it. User-owned private repositories still publish the image but record the unsupported attestation in the release summary.
