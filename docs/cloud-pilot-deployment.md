# MINAI Cloud Pilot Deployment

This is the deployment path for the first controlled Road shadow pilot. The operator uses MINAI from an ordinary browser; the application, state, verified operational data and Outlook delegated-auth cache remain on the controlled cloud service.

## Pilot topology

- One cloud web-service instance only.
- Public browser entry is HTTPS only.
- Railway is the initial pilot host; use EU West (Amsterdam).
- Railway terminates public TLS and forwards to the container.
- `src.cloud_pilot_launcher` forces the container to bind on `0.0.0.0:$PORT` and enables the explicit edge-HTTPS trust boundary.
- MINAI remains in `shadow` outbound mode. Cloud deployment does not authorize autonomous customer or supplier sends.
- A persistent Railway volume must be mounted at `/data` before real pilot state is created.
- SQLite, the verified operational pack and the Outlook token cache must remain under `/data`.
- Keep the service at one replica while SQLite + one attached volume are the pilot persistence model.

## Repository deployment contract

Railway builds the repository with the root `Dockerfile`. The container starts:

```text
python -m src.cloud_pilot_launcher
```

The cloud launcher:

1. reads the platform `PORT`,
2. forces `MINAI_PILOT_BIND_HOST=0.0.0.0`,
3. forces `MINAI_PILOT_EDGE_HTTPS=1`,
4. refuses non-shadow outbound mode,
5. refuses pilot DB/data/token-cache paths outside the persistent storage root,
6. delegates all remaining fail-closed validation to the normal controlled pilot launcher.

Do not run a development server, `--reload`, Streamlit, or an alternate Uvicorn command for the real pilot.

Before starting or after any deployment-variable/storage change, validate the live cloud environment without starting an alternate runtime:

```text
python -m src.cloud_pilot_launcher --check-only
```

The output is intentionally limited to non-secret transport/persistence fields. A failed check is NO-GO.

## Railway setup

Create a Railway service from the GitHub repository and select the controlled release branch/commit. For the real pilot, deployment must be tied to the exact release commit that passes Day 0 readiness.

Use these service settings:

- Region: EU West / Amsterdam.
- Replicas: 1.
- Volume mount: `/data`.
- Public Networking: generate one Railway HTTPS domain initially; a custom MINAI domain may be added later.
- Disable automatic production deploys during the controlled pilot. Promote/deploy only an explicitly reviewed exact release commit; a later merge must not silently replace the running release.
- Do not expose a second raw TCP/public application port.

The repository Dockerfile is the build authority. No Railway-specific config-as-code file is required.

## Runtime variables

All real values belong in Railway Variables/Secrets or the persistent volume, never in Git.

Required pilot/runtime values include:

```text
MINAI_PILOT_MODE=1
MINAI_OUTBOUND_MODE=shadow
MINAI_PILOT_BASE_URL=https://<generated-or-approved-domain>
MINAI_PILOT_ALLOWED_NETWORKS=127.0.0.1/32
MINAI_PILOT_OPERATORS_JSON=<named bearer operators JSON>

MINAI_WEB_SHELL_ENABLED=1
MINAI_WEB_SESSION_SECRET=<random secret, at least 32 characters>
MINAI_WEB_USERS_JSON=<named browser users with supported password hashes>

MINAI_CLOUD_STORAGE_ROOT=/data
MINAI_PILOT_DB_PATH=/data/state/minai_pilot.sqlite3
MINAI_PILOT_DATA_DIR=/data/operational
MINAI_PILOT_RETENTION_DAYS=365

OPENAI_API_KEY=<approved secret>
MINAI_OUTLOOK_TENANT_ID=<approved tenant UUID>
MINAI_OUTLOOK_CLIENT_ID=<approved public client UUID>
MINAI_OUTLOOK_MAILBOX_ID=<approved pilot mailbox>
MINAI_OUTLOOK_TOKEN_CACHE_PATH=/data/auth/outlook-token-cache.json
```

`MINAI_PILOT_EDGE_HTTPS`, `MINAI_PILOT_BIND_HOST` and `MINAI_PILOT_PORT` are transport values owned by the cloud launcher and platform. Do not override them manually for the controlled cloud pilot.

## Persistent data bootstrap

Before launch, create/upload the external pilot material under `/data`:

```text
/data/
  operational/        verified customer/supplier pilot data pack
  state/              fresh real-pilot SQLite state
  auth/               Outlook delegated token cache
  evidence/           external readiness/replay evidence if hosted here
  backup/             controlled pilot backups
```

The real pilot must start with a fresh SQLite database. Development/smoke databases must not be copied into `/data/state/minai_pilot.sqlite3`.

The verified operational pack must be the final approved pack bound to the release readiness evidence. Do not bake customer/supplier operational data, OpenAI keys, Microsoft tokens or web credentials into the Docker image.

## Browser users for first pilot

Initial intended browser identities:

- Sibel — named daily operator. Add her full surname before Day 0 readiness attestation.
- Tan Yuregir — Pilot Owner / Senior Road Reviewer / stop authority.

Each person gets a separate browser login. Shared credentials are not permitted.

## Outlook first authorization

Outlook delegated auth uses the existing Microsoft device-flow path. Perform the first authorization only after the approved mailbox and tenant/client IDs are configured. The resulting token cache must be written to `/data/auth/outlook-token-cache.json` so it survives redeploys.

No real mailbox pull is authorized merely by deploying the service. Real-mail access still follows the Day 0 gate and selected real-mail authorization.

## Day 0 cloud gate

Cloud hosting changes the transport/deployment evidence, not the controlled-pilot safety sequence. Before `REAL SHADOW PILOT: GO`:

1. freeze the exact cloud release commit,
2. verify one-instance + persistent-volume configuration,
3. verify HTTPS login for both named users,
4. verify runtime health and release identity,
5. verify fresh persistent SQLite state,
6. verify exact operational-data hashes,
7. run the exact-release technical gates,
8. run authorized sanitized replay and create its receipt,
9. record the seven already-existing readiness approvals,
10. build and validate final readiness evidence.

Only then may the first selected real mailbox message be processed.

## Update discipline during pilot

A cloud deploy makes updates easier, but it does not permit live editing of the pilot. A safety-critical problem follows the normal sequence: stop affected processing, reproduce, fix on a fresh branch, run focused + canonical regressions, pass CI, obtain explicit merge approval, create a new exact release and repeat any release-bound readiness evidence that became stale.

Minor UX observations should be logged rather than patched continuously during the working day unless they block safe use.
