# Security policy

## Reporting

Do not open a public issue for a suspected vulnerability. Contact the repository owner privately with the affected version, reproduction steps, and impact.

## Deployment boundary

- Keep the repository private until deployment secrets and identity configuration are established.
- Never commit `.env.deploy`, API keys, identity-provider secrets, database exports, uploaded documents, or the `work/` directory.
- The `demo` profile is for non-sensitive evaluation data. Real user data requires the production identity profile, a retention policy, backups, monitoring, and infrastructure-level encryption.
- External sends, publishes, payments, and investments are not executed by this application. Approval records do not imply connector execution.
