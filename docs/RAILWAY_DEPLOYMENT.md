# Railway private-beta deployment

The Railway project already contains an EdgeIQ service, a PostgreSQL service, and
the domain `edgeiq-production-74ba.up.railway.app`. As checked on October 1, 2026,
the web service has no active deployment. It is configured for the repository
Dockerfile, Alembic pre-deploy migration, `/api/health`, one replica, and an
always-awake runtime. Hosted mode and the allowed origin are set; the private
access password has not been verified. Do not create a second project or service.

## Before deploying

1. Review and publish the intended Git commit to the service's configured `main`
   branch. The current deploy-ready Dockerfile is on the feature branch, not the
   last locally known `origin/main`; local uncommitted code is not in Railway builds.
2. Back up the production PostgreSQL database before applying migrations.
3. Set `DATABASE_URL` to a reference to the PostgreSQL service, not a SQLite URL.
4. Set `EDGEIQ_DEPLOYMENT_MODE=hosted`,
   `EDGEIQ_ALLOWED_ORIGINS=https://edgeiq-production-74ba.up.railway.app`, and a
   strong, unique `EDGEIQ_HOSTED_ACCESS_PASSWORD`. Optionally set
   `EDGEIQ_HOSTED_ACCESS_USER` (defaults to `edgeiq`). Keep the password in
   Railway variables; never commit it or send it in a chat.
5. Confirm the service still builds with the repository Dockerfile, runs
   `python -m alembic upgrade head` before deployment, and uses `/api/health`
   as its healthcheck path. Its configured shell start command expands Railway's
   `PORT`: `sh -c 'exec uvicorn web.app:app --host 0.0.0.0 --port ${PORT:-8080}'`.
6. Keep one web replica while its in-process scheduler is enabled. Schedule work
   is not durable across deploys; a separate hosted worker and cross-process
   locking are required before scaling replicas or promising unattended runs.

The Docker image installs `requirements-web.txt`, including Alembic and psycopg3,
without desktop Qt packages. It excludes local databases and `.env` files.
`/api/health` is public only when the hosted access password is configured;
every other route requires HTTP Basic authentication. This is for a private,
single-operator beta. Beta accounts do **not** yet isolate the main entry and
research APIs by user, so do not sell multi-user access on this configuration.

After deploying, check the build and pre-deploy logs, confirm `/api/health`
returns 200, confirm the app prompts for credentials, then verify `/api/version`,
Today, and a read-only Results view after sign-in. Do not start provider scans or
repair historical entries until the deployed database and provider credentials
have been verified. Configure off-device PostgreSQL backups and test restoration
before using this as the sole copy of paid-entry records.
