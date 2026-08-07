# Deployment guide

This repository is packaged as one application because Tyche, Plutus, and Nous share the same API, policy layer, identity boundary, storage abstraction, and browser client.

## Public demo profile

The supplied Compose profile runs an isolated guest demo behind PostgreSQL. Each browser tab receives a signed 24-hour guest identity and a separate workspace. This is suitable for product evaluation, not for storing regulated or sensitive information.

Prerequisites on the deployment host:

- Docker Engine with the Compose plugin
- a reverse proxy such as Caddy or Nginx
- DNS access for `buildquick.co.in`
- outbound access to GitHub Container Registry only if you later publish images there

Clone the private repository and create an ignored deployment environment file:

```bash
git clone https://github.com/sachinkamath-PM/parallel-copilots.git
cd parallel-copilots
cp .env.example .env.deploy
```

Generate independent URL-safe secrets and set at least these values in `.env.deploy`:

```dotenv
APP_SECRET=replace-with-at-least-32-random-bytes
POSTGRES_PASSWORD=replace-with-a-url-safe-random-password
ALLOWED_HOSTS=buildquick.co.in,www.buildquick.co.in,localhost,127.0.0.1
ASSISTANT_PROVIDER=mock
```

Avoid punctuation that needs URL encoding in `POSTGRES_PASSWORD`, because Compose constructs `DATABASE_URL` from it.

Start and verify the services:

```bash
docker compose --env-file .env.deploy up -d --build
docker compose ps
curl http://127.0.0.1:8000/api/health
```

The application binds only to loopback. Terminate TLS at the reverse proxy and forward `https://buildquick.co.in` to `http://127.0.0.1:8000`. For Caddy, the site block is:

```caddyfile
buildquick.co.in, www.buildquick.co.in {
    reverse_proxy 127.0.0.1:8000
}
```

Create `A`/`AAAA` records for the domain before starting Caddy so it can obtain certificates. Redirect the `www` hostname to the preferred canonical hostname if desired.

## Privacy and retention

- Do not upload real financial records, résumés, or confidential research to a public demo.
- Extracted upload contents are stored in PostgreSQL; original files are not retained.
- Guest workspaces are isolated but are not automatically expired from the database yet.
- To erase all demo data, stop the stack and deliberately remove the `parallel-copilots_postgres-data` volume. This is destructive and should only be done after backups are considered.
- Use an identity provider and formal retention process before allowing real customer data.

## Production identity profile

For a real authenticated deployment, use `APP_ENV=production`, `AUTH_MODE=introspection`, an HTTPS `IDENTITY_INTROSPECTION_URL`, PostgreSQL, explicit `ALLOWED_HOSTS`, and a strong `APP_SECRET`. The browser login flow must be integrated with the chosen identity provider before this profile can be used through the bundled UI.

Set `ASSISTANT_PROVIDER=openai` only when `OPENAI_API_KEY` is supplied through the host's secret manager. The deterministic mock provider requires no external AI API.

## Updating and rollback

```bash
git fetch --tags origin
git checkout <release-tag>
docker compose --env-file .env.deploy up -d --build
```

Rollback by checking out the previous signed-off tag and rebuilding. Back up PostgreSQL before deploying migrations or making destructive operational changes.
