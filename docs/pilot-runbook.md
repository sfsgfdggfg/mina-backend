# MINAI Controlled Shadow Pilot Runbook

This runbook is for the controlled, human-operated shadow pilot. MINAI drafts
and records workflow state; the real logistics operation remains authoritative.
MINAI does not send supplier RFQs or customer quotes in this workflow.

## A. Before Startup

Use only the validated runtime: Python 3.12.1 (the supported family is Python
3.12). From the repository root, install the committed controlled-pilot lock
and verify it before the regression gate:

```bash
python --version
python -m pip install -r requirements-lock.txt
python -m src.runtime_preflight
python -m pip check
```

The preflight is offline and checks only the Python family plus required pilot
runtime package imports and versions; it does not read or print secrets and
does not authorize real-data use. `requirements-dev.txt` is only for the
optional development UI. Streamlit remains off and is not pilot-approved.

The release owner must record the approved pilot commit SHA in the external
change record and verify it before startup:

```bash
git rev-parse HEAD
```

Do not start if it differs from the externally approved SHA. The P0.13 work is
based on `189a767` (`Complete P0.12 manual RFQ sent evidence`), but that baseline
is not a substitute for release approval of the final pilot commit.

Configure the server through the approved secret/deployment mechanism, never a
committed file:

```env
MINAI_PILOT_MODE=true
MINAI_PILOT_BIND_HOST=<actual-private-or-loopback-IP>
MINAI_PILOT_PORT=8000
MINAI_PILOT_ALLOWED_NETWORKS=<approved-private-or-loopback-CIDRs>
MINAI_PILOT_OPERATORS_JSON={"Named Operator":"<unique-secret-at-least-32-characters>"}
MINAI_PILOT_DB_PATH=data/pilot/minai_pilot.sqlite3
MINAI_PILOT_RETENTION_DAYS=30
```

Every token must belong to one named operator. Confirm restrictive host and
storage permissions before loading real data. Streamlit is not pilot-approved.
Outbound supplier/customer delivery must remain disabled; manual activity is
performed in the real logistics systems and only recorded in MINAI.

Before any real email, confirm all required operational datasets are currently
`pilot_verified`, `pilot_usable`, attributed to a verifier, timestamped, and
fingerprint-matched. Also confirm explicit organizational/legal approval for
real-data use with OpenAI.

The three validation layers are distinct:

1. Run the canonical regression gate:

```bash
python -m src.simulation.pilot_regression_suite
```

2. Run the full deterministic, offline synthetic controlled-pilot rehearsal:

```bash
python -m src.simulation.pilot_rehearsal
```

3. Before a future real-data pilot, run the separately authorized sanitized
historical replay when that capability and its approvals exist.

The temporary synthetic `pilot_verified` data used by the rehearsal authorizes
only that isolated rehearsal. It does not authorize or relabel repository data;
the repository demo data remains unverified. A real pilot still requires P0.14
real verified customer and supplier datasets, plus all required organizational,
deployment, privacy, legal, and real-data approvals. The canonical gate and
synthetic rehearsal do not replace the future sanitized historical replay.
Any missing prerequisite is NO-GO.

### Sanitized Historical Replay

The synthetic controlled-pilot rehearsal and authorized sanitized historical
replay are different validation layers. The rehearsal uses generated temporary
cases to exercise lifecycle controls. Historical replay evaluates extraction and
operational-decision evidence against operator-confirmed truth from
pre-sanitized historical inquiries.

The provider-neutral harness remains offline-safe:

```bash
python -m src.simulation.sanitized_replay \
  --input /approved/external/path/replay.jsonl
```

That CLI validates the external replay contract and intentionally does not
invoke a production provider. The provider-neutral module also exposes the
injected replay runner used by deterministic regressions. It does not authorize
production AI use.

The explicitly authorized production-parser boundary is separate:

```bash
python -m src.simulation.authorized_sanitized_replay \
  --input /approved/external/path/replay.jsonl \
  --confirm-pre-sanitized \
  --confirm-openai-data-use-approved \
  --confirm-no-autonomous-outbound
```

The three confirmations are mandatory. They are operational assertions, not
software proof of legal or organizational approval. Do not run the authorized
command until the responsible organization has approved the replay and the
configured OpenAI data use.

There is no default replay input. The JSONL must be pre-sanitized and stored
outside the repository. Repository paths are rejected. Each line contains
`schema_version` (`"1.0"`), a pseudonymous `case_id`, `.invalid`
`sender_address` (and optional `sender_domain`), sanitized `subject` and
`body_text`, and `expected`. `expected.facts` represents operator-confirmed
historical truth with `known`, `unknown`, or `not_applicable` states.

Defensive validation rejects suspicious normal email domains, phone numbers,
Turkish IBANs, and non-pseudonymous expected customer identifiers. This is a
fail-closed check and is not a claim of perfect anonymization. Never place raw
historical email, real contact addresses, customer names, supplier contact
values, tokens, or secrets in the replay JSONL.

The authorized adapter applies the production privacy transform before the
production AI parser. AI extraction output is scored as proposal evidence only.
It is not promoted directly into the operational workflow. Downstream replay
uses the operator-confirmed historical expected facts as the confirmed shipment,
which preserves the mandatory human extraction-confirmation boundary. If a
required safety fact is unknown, the replay stops at
`extraction_confirmation_required`.

The same external pilot operational data pack used for pilot decisions must be
selected through `MINAI_PILOT_DATA_DIR`. Customer memory and supplier
capabilities must be `pilot_verified`, exact-fingerprint valid, structurally
valid, and usable for the controlled pilot. Repository/demo datasets do not
qualify. Supplier/customer autonomous outbound must remain disabled.

For durable technical evidence, request a create-only external receipt:

```bash
python -m src.simulation.authorized_sanitized_replay \
  --input /approved/external/path/replay.jsonl \
  --confirm-pre-sanitized \
  --confirm-openai-data-use-approved \
  --confirm-no-autonomous-outbound \
  --receipt /approved/external/path/replay-receipt.json
```

Receipt creation requires a clean Git worktree. The receipt binds safe aggregate
results to the exact Git commit, replay-input SHA-256, verified customer-memory
SHA-256, verified supplier-capabilities SHA-256, and active privacy-transform
version. Replay input and operational-data fingerprints are checked across the
execution boundary; mutation blocks receipt creation. The destination must be
an absolute external path and an existing receipt is never overwritten.

The receipt contains aggregate metrics only. It must not contain replay case
values, sender/customer identities, message text, contact values, tokens, or
other secrets. Its
`customer_identity_mode=pseudonymous_replay_no_trusted_sender_assertion`
explicitly records a limitation: sanitized historical replay does not prove the
production trusted-sender/customer-memory identity path.

A passing receipt requires a non-failing replay result and zero
safety-critical mismatches for GO evidence. It is still only technical replay
evidence. It does not replace organization, privacy/legal, OpenAI data-control,
deployment/storage, retention/deletion, named-operator, or senior-road-reviewer
approval, and it does not by itself authorize the real pilot.

Results distinguish field extraction outcomes, workflow decisions, equipment
decisions, supplier progression, and safety failures. ADR or
temperature-control truth lost, an excluded/high-value/project or non-road case
allowed, or supplier progression despite a required clarification or stop is
safety-critical. Every such mismatch must be investigated with the logistics
operator before pilot GO.

Configure the operator terminal without saving the token in source control,
shell scripts, command arguments, or command history:

```bash
export MINAI_PILOT_BASE_URL='http://127.0.0.1:8000'
export MINAI_PILOT_TOKEN='<token-from-approved-secret-store>'
```

The base URL accepts only localhost or an explicit private/loopback IP. Plain
HTTP carries a bearer credential and is allowed only on loopback or an approved
trusted private network/VPN. Use HTTPS where the approved deployment provides
it.

### Read-Only Outlook Inbound Setup

The controlled pilot may read customer inquiries directly from one approved
Microsoft 365 / Outlook mailbox through Microsoft Graph.

This capability is inbound-only. The Microsoft application uses delegated
`Mail.Read` permission. Do not grant `Mail.ReadWrite`, `Mail.Send`,
application-wide mailbox permissions, or any other outbound/mailbox-write
permission for this pilot.

Configure the pilot host through the approved secret/deployment mechanism:

```env
MINAI_OUTLOOK_TENANT_ID=<approved-microsoft-tenant-uuid>
MINAI_OUTLOOK_CLIENT_ID=<approved-public-client-application-uuid>
MINAI_OUTLOOK_MAILBOX_ID=<approved-pilot-mailbox-sign-in-address>
MINAI_OUTLOOK_TOKEN_CACHE_PATH=/approved/external/minai-pilot/secrets/outlook-token-cache.json
```

The token-cache path must be absolute, outside the repository, and protected
from other users. Existing cache files with group/other permissions are
rejected on POSIX systems. The cache contains Microsoft authentication material
and must be handled as a secret.

The Microsoft application must be configured as a public client capable of the
device-code flow. MINAI does not require or store a Microsoft client secret for
this delegated pilot integration.

Perform the initial Microsoft authorization, or an explicit reauthorization,
on the pilot host:

```bash
python -m src.outlook_auth
```

Follow the Microsoft device-login instruction printed by the command and sign
in only as the exact mailbox identity configured by
`MINAI_OUTLOOK_MAILBOX_ID`. A different authorized account is rejected.

The authorization command may display the Microsoft device-login instruction
and one-time device code. It must not print access tokens, refresh tokens, or
the serialized token cache.

Normal operator pulls use silent authentication from the server-side cache.
The MINAI operator terminal never receives the Microsoft Graph token.

Microsoft Graph access remains deliberately narrow:

- inbox messages are read with HTTP GET only;
- message IDs are requested as immutable IDs for durable deduplication;
- message bodies are requested as text;
- redirects are refused;
- each operator pull is explicitly bounded to 1-50 messages;
- MINAI does not mark mail as read, move it, delete it, flag it, reply to it, or
  send any message;
- P1-19 does not add webhooks, subscriptions, polling daemons, or background
  autonomous mailbox monitoring.

Before using Outlook inbound with real customer mail, the configured
`MINAI_PILOT_DATA_DIR` must select the approved external pilot operational data
pack. Customer-memory provenance and trusted-sender records remain part of the
safety boundary.

## B. Starting the Pilot

From the repository root, start only the safe launcher:

```bash
python -m src.pilot_launcher
```

Do not add `--reload`, do not use the development Uvicorn command, and do not
start Streamlit. Successful startup validates the pilot configuration before
Uvicorn reports that it is running on the exact configured host and port.

From the operator terminal, verify health and authentication configuration:

```bash
python -m src.pilot_operator status
```

Expected result includes a health `"status": "ok"` and
`"authentication": "ok"`. The client verifies the token through an
authenticated read because the server health route itself is authentication
exempt. Successful status does not authorize real data; all GO/NO-GO controls
still apply.

## C. Operator Workflow

Keep the printed identifiers in the approved external pilot log. They make the
workflow recoverable without guessing IDs.

1. Pull the approved Outlook inbox from the authenticated operator terminal:

   ```bash
   python -m src.pilot_operator outlook pull --limit 10
   ```

   The operator command talks only to the authenticated MINAI API. Microsoft
   authentication and Graph access remain server-side.

   For each fetched message, the server first enforces the controlled inbound
   gate. A message reaches AI extraction only when all of the following are
   true:

   - it came from the server-side Microsoft Graph adapter with complete provider
     metadata;
   - it has no attachments;
   - the configured external customer-memory dataset is currently verified;
   - the sender matches exactly one active pilot customer through an explicitly
     trusted sender address or domain.

   Untrusted or ambiguous senders stop before the AI parser. Messages with
   attachments return `inbound_mail_manual_review_required`; attachments are not
   downloaded or interpreted by P1-19. A provenance failure also stops before
   parsing.

   A permitted message passes through the existing privacy transform before the
   AI parser. AI output remains only an extraction proposal and cannot enter the
   operational workflow without the existing explicit human confirmation.

   The pull response intentionally contains only a minimal operational summary:
   immutable external message ID, received time, result/ingestion state,
   safe reason code when applicable, and proposal ID when one exists. It does
   not return the raw customer body, sender identity, or Microsoft token.

   Re-pulling the same Outlook message is safe. Deduplication uses Microsoft
   Graph provider identity, mailbox identity and immutable message ID. An
   existing identical message returns the existing proposal without a second AI
   parse. Reuse of the same message ID with different content or sender is
   blocked as a conflict.

   Record every returned `proposal_id` that requires review. `mailbox_write_performed=false`
   and `automated_send_performed=false` are the expected controlled-pilot
   invariants.

   If the pull returns an Outlook reauthentication requirement, stop and have an
   authorized person run `python -m src.outlook_auth` on the pilot host. Do not
   place Microsoft tokens in command-line arguments, operator environment
   variables, chat, source files, or the pilot log.

   The existing manual inbound path remains an explicit fallback when the
   approved Outlook integration is unavailable or a message must be handled
   manually. Save the inbound body in a temporary operator-controlled file and
   submit it as manual source data:

   ```bash
   python -m src.pilot_operator process-email \
     --body-file /approved/input/customer-email.txt \
     --sender-address customer@example.invalid \
     --sender-name 'Customer Contact' \
     --subject 'Freight request' \
     --external-message-id 'mailbox-reference'
   ```

   Manual submission cannot claim Microsoft Graph provider identity. Remove the
   temporary raw-email file according to the approved real-data handling
   procedure after submission.

2. Re-read the proposal whenever needed:

   ```bash
   python -m src.pilot_operator proposal get <proposal_id>
   ```

3. Confirm it with explicit corrections. JSON booleans are lowercase. Include
   every unresolved safety fact and correct `transport_mode` when necessary:

   ```bash
   python -m src.pilot_operator proposal confirm <proposal_id> \
     --corrections '{"transport_mode":"road","is_adr":false,"is_temperature_controlled":false,"is_high_value":false}'
   ```

   The server records the authenticated token owner, not an identity supplied
   by the command.

4. Resume the confirmed extraction:

   ```bash
   python -m src.pilot_operator proposal resume <proposal_id>
   ```

   Record `supplier_rfq_workflow.workflow_id` and every
   `supplier_rfq_drafts[].rfq_id`. If the result is scope- or
   provenance-blocked, stop and follow section D.

5. Review RFQs and approve only the intended draft:

   ```bash
   python -m src.pilot_operator rfq list
   python -m src.pilot_operator rfq get <rfq_id>
   python -m src.pilot_operator rfq approve <rfq_id>
   ```

6. Send the approved RFQ outside MINAI using the authoritative logistics
   operation. Only after that external action succeeds, record it in MINAI:

   ```bash
   python -m src.pilot_operator rfq manual-sent <rfq_id>
   ```

   Confirm the returned status is `awaiting_response` and record the evidence
   timestamp. This command does not send an email.

7. When the supplier response arrives, enter it. For a quote, cost and currency
   are required:

   ```bash
   python -m src.pilot_operator rfq response <rfq_id> \
     --supplier-name 'Supplier Name' \
     --priority 1 \
     --status quoted \
     --cost 1500 \
     --currency EUR \
     --transit-time '3 days' \
     --validity-date '2026-08-31'
   ```

   Other statuses are `no_capacity`, `declined`, and `needs_clarification` and
   must not include quote cost/currency.

8. Resume quote progression with the recorded workflow ID:

   ```bash
   python -m src.pilot_operator workflow resume-quote <workflow_id>
   ```

   Record `quote_approval.approval_id` and `quote_case.case_id`.

9. Review the current customer quote case and its current approval:

   ```bash
   python -m src.pilot_operator approval list
   python -m src.pilot_operator approval get <approval_id>
   python -m src.pilot_operator case list
   python -m src.pilot_operator case get <case_id>
   ```

   The AI-generated customer email is an editable draft. If the subject, body,
   tone, wording or customer sales price needs to change, revise the case before
   final approval:

   ```bash
   python -m src.pilot_operator case revise <case_id> \
     --approval-id <current_approval_id> \
     --subject 'Revised customer quote subject' \
     --body-file /approved/input/revised-customer-quote.txt
   ```

   `--final-price <amount>` and `--note 'Operator note'` may be supplied when
   needed. A revision never sends an email. It invalidates any pending or
   approved authority for the previous version and creates a fresh pending
   approval for the exact revised subject, body and structured customer price.

   Record the returned `new_approval.approval_id`, then re-read the case and the
   fresh approval. Never approve an older approval ID after a revision.

10. Approve only the current quote version:

   ```bash
   python -m src.pilot_operator case get <case_id>
   python -m src.pilot_operator approval get <current_approval_id>
   python -m src.pilot_operator approval approve <current_approval_id>
   ```

   The available alternative decisions are:

   ```bash
   python -m src.pilot_operator approval reject <current_approval_id> --reason 'Reason'
   python -m src.pilot_operator approval invalidate <current_approval_id>
   ```

   After approval, re-read the case if needed. The current approval and current
   quote snapshot must still match. Any later revision requires a new approval.

11. Produce the final read-only customer quote handoff:

   ```bash
   python -m src.pilot_operator case final <case_id>
   ```

   This command is available only when the current customer quote has a valid
   current human approval and the approved snapshot matches the current case.
   The output contains the exact approved customer-facing `subject`, `body`,
   structured `final_price`, currency and approval metadata.

   Copy the approved subject and body into the authoritative external logistics
   email system and perform the real customer delivery there under normal
   operational controls.

   `delivery_mode=manual_external_operation` and
   `automated_send_performed=false` are the expected controlled-pilot state.
   `case final` does not send, schedule or prepare an autonomous customer email.

   If the case is edited after approval, the previous approval loses authority
   and `case final` remains blocked until the fresh revised approval is approved.

## D. Common Blocks and Errors

The client prints a short safe message and no traceback by default:

| Result | Meaning and action |
| --- | --- |
| `data_provenance_blocked` | Stop. A technical/data owner must repair and re-verify the required dataset. The documented blocked resume may be retried only after repair. |
| `pilot_scope_excluded` | Stop MINAI handling for this shipment. Continue only in the authoritative logistics operation. |
| 401 | Token missing, invalid, or assigned incorrectly. Fix authentication; do not retry a state change blindly. |
| 403 | Client address is outside the allowed network. Stop and contact the deployment owner. |
| 404 | ID is wrong, resource is absent, or route is pilot-disabled. Use read/list commands; do not guess IDs. |
| 409 | State conflict, duplicate, or stale attempt. Read the resource first. Do not repeat unless its current state proves the action did not commit. |
| 428 | Outlook delegated authorization is missing or expired. Stop the pull and perform explicit host-side reauthorization with `python -m src.outlook_auth`; do not bypass authentication. |
| 422 | Input/correction violates the model. Correct the input after reviewing the proposal/RFQ. |
| 503 | Pilot configuration, provenance, or system safety block. Stop until an authorized owner resolves it. |

Safe reads (`status`, `proposal get`, RFQ/approval/case list/get`, and
`case final`) may be repeated.
State-changing commands are never silently retried by the client. After an
interruption, read current state before deciding whether any action is safe.

## E. Emergency Stop

1. Stop the launcher process with the process supervisor or `Ctrl-C`.
2. Do not continue handling the email in MINAI.
3. Continue operational handling only in the authoritative real logistics
   operation under its normal controls.
4. Record the incident, affected MINAI IDs, operator, and time outside MINAI.
5. Do not restart until the authorized incident/deployment owner approves it.

## F. Backup and Recovery

The default database is `data/pilot/minai_pilot.sqlite3`; an explicit
`MINAI_PILOT_DB_PATH` overrides it. It contains privacy-minimized operational
state and evidence and must remain on approved restricted storage.

For a simple safe offline backup:

1. Stop the launcher and confirm the process is no longer running.
2. With no writer active, use the approved host backup tool to copy the database
   and any same-name `-wal` and `-shm` sidecar files together into restricted
   backup storage. Do not copy a live database file by itself.
3. Preserve ownership and restrictive permissions; never commit the backup.
4. Restore the complete stopped-state file set to the configured path.
5. Start with `python -m src.pilot_launcher`, run `status`, and use proposal/RFQ/
   approval/case reads to verify known IDs before resuming work.

Where the `sqlite3` command is approved and installed, its `.backup` command is
also SQLite-supported, but it does not remove the requirement for restricted
backup storage and restore verification. This runbook does not install or
schedule a backup system.

## G. Retention

`MINAI_PILOT_RETENTION_DAYS` defaults to 30 and accepts 1 through 365 days.
Expired current-state records and evidence events are purged when
`SQLitePilotStore` initializes, including application startup. There is no
scheduled background purge.

The technical owner can verify the purge contract with sanitized temporary data:

```bash
python - <<'PY'
from src.simulation.privacy_boundary_regressions import evaluate_privacy_boundary_regressions
result = evaluate_privacy_boundary_regressions()
print(result)
raise SystemExit(0 if result["passed"] else 1)
PY
```

Do not use production records to test retention. Operational verification of a
particular deployment’s purge must follow the approved evidence-review process.

## H. GO/NO-GO Reminders

The pilot is NO-GO unless all are true:

- the running SHA is explicitly approved;
- all required real operational datasets are `pilot_verified` and fingerprint-valid;
- real-data/OpenAI use has explicit organizational, legal, and contractual approval;
- bind host, firewall/VPN, and allowed networks are approved;
- database, backups, logs, and host access have restricted permissions;
- unique named operator tokens are provisioned outside source control;
- outbound delivery remains disabled in MINAI;
- Streamlit remains off;
- the canonical controlled-pilot regression gate passed;
- a complete sanitized replay passed before the first real email.

## Pilot Readiness Assessment

Run the offline, fail-closed release assessment from the repository root:

```bash
python -m src.pilot_readiness
```

The command runs runtime preflight, the canonical regression gate, and the
synthetic full rehearsal. It also verifies the current Git commit, requires a
clean worktree, and uses the production provenance validator for
`customer_memory` and `supplier_capabilities`. `--no-run-gates` is diagnostic
only: skipped gates are `NOT RUN` and can never produce GO.

Technical evidence proves that this repository can verify its implemented
controls. It does not prove organizational, privacy, legal, OpenAI data-use,
deployment/storage, retention, operator, or reviewer approval. Those items
remain `NOT VERIFIED` without an explicit external human-attestation file. The
replay harness capability is also separate from an actual authorized sanitized
historical replay; without an attested execution, replay is `NOT RUN`.

The current repository is expected to report NO-GO until P0.14 has produced
fingerprint-valid `pilot_verified` operational data and all approvals and replay
evidence are current. This expected exit code is `1`. Invalid invocation or an
unsafe/malformed evidence file exits `2`; GO exits `0`. There is no numeric
readiness score: every mandatory prerequisite must pass.

Readiness evidence must be stored outside the repository.
Do not manually construct or transcribe the readiness JSON.

After an authorized sanitized historical replay has produced a passing
external `replay-receipt.json`, build the readiness evidence with the
guided builder:

```bash
python -m src.pilot_readiness_evidence build \
  --replay-receipt /approved/external/path/replay-receipt.json \
  --output /approved/external/path/readiness-evidence.json
```

The builder fails closed before collecting human attestations unless all
of the following are true:

- the Git worktree is clean;
- the replay receipt is bound to the exact current Git commit;
- the replay result is `pass`, contains at least one case, and has zero
  safety-critical mismatches;
- the configured external pilot operational data pack is
  production-verified;
- the exact SHA-256 fingerprints of `customer_memory` and
  `supplier_capabilities` match the fingerprints recorded in the replay
  receipt.

The builder then requests each required human approval interactively.
The operator must type the exact word `CONFIRM` for every approval and
identify the role or person that already granted it.

The seven independent attestations are:

- organization approval;
- privacy/legal approval;
- OpenAI data-control approval;
- deployment/storage approval;
- retention/deletion procedure approval;
- named operators confirmation;
- senior road reviewer confirmation.

The builder records approvals that already exist. It does not grant
approval, perform legal review, authorize the pilot, or start the real
shadow pilot.

Generated readiness evidence uses schema version 2.

It binds the evidence to:

- the exact pilot Git commit;
- `customer_memory` SHA-256;
- `supplier_capabilities` SHA-256;
- the validated sanitized replay result.

Legacy schema version 1 readiness evidence is rejected because it does
not bind replay evidence to the exact operational data pack.

The output path must be absolute and outside the repository.
Existing evidence files are never overwritten. On POSIX systems the
generated file is owner-only (`0600`).

Never include raw mail, replay cases, customer/supplier records,
passwords, API keys, tokens, or other secret/raw operational values in
readiness evidence.

After creating the evidence file, run:

```bash
python -m src.pilot_readiness \
  --evidence /approved/external/path/readiness-evidence.json
```

A stale commit, dirty worktree, changed operational data pack, failed
live gate, failed provenance check, missing approval, failed replay, or
critical replay mismatch blocks GO.

Keep `replay-receipt.json` and `readiness-evidence.json` together in the
approved external evidence location for audit review.

`EXPECTED DISABLED` for automated supplier RFQ and customer quote outbound is
the correct controlled-pilot state and is non-blocking. Enabling either is a
block. The allowed scope remains road-only, one pilot logistics firm, and human
operated, with no autonomous outbound. ADR, reefer/temperature-controlled,
medical/pharma, chemical, high-value, oversize/project, multimodal, and
mixed-currency work remain excluded by the existing pilot policy and regression
coverage.

## External Pilot Operational Data Pack

Real controlled pilot operational master data must stay outside Git. Prepare one
approved external pack root with this exact layout:

```text
/approved/external/minai-pilot/
└── data/
    ├── customer_memory.json
    ├── supplier_capabilities.json
    └── provenance_registry.json
```

Point the process at the **pack root**, not the `data/` directory:

```bash
export MINAI_PILOT_DATA_DIR=/approved/external/minai-pilot
```

The controlled pilot launcher requires this variable. Development may continue
to use repository demo/default data when it is unset, but that fallback is not
accepted by the real pilot launcher.

Before startup, keep the pack outside the repository and do not use symlinks to
redirect `data/` or a required dataset back into the repository. Do not put raw
mail, tokens, passwords, API keys, or unapproved master data in the pack.

The pack selection itself is not authorization. `customer_memory` and
`supplier_capabilities` must still be `pilot_verified`, operational,
pilot-usable, and exact-fingerprint valid in `provenance_registry.json`.

Run readiness with the same environment that will launch the pilot:

```bash
python -m src.pilot_readiness   --evidence /approved/external/path/readiness-evidence.json
```

Only after readiness is GO should the controlled launcher be used:

```bash
python -m src.pilot_launcher
```

Readiness and the API resolve the same operational source set. Extraction
resume and supplier RFQ quote progression cannot accept remote filesystem path
overrides; operational data source selection is deployment-local only.

## P1-20 Addendum — Controlled Outlook Supplier Replies

P1-20 extends the existing explicit read-only Outlook pull so the same approved
mailbox pull can handle both trusted pilot customer inquiries and supplier RFQ
replies. The P1-19 customer-only routing description remains historical; this
addendum defines the current controlled inbound behavior.

Every Graph message is still required to carry complete server-created
Microsoft Graph provenance and to have no attachments before routing begins.
Attachments remain manual-review-only.

Routing is deterministic and occurs before any AI parser:

- an exactly trusted active pilot customer sender may enter the existing customer
  inquiry path;
- a supplier sender may enter the supplier-response path only when existing RFQ
  lifecycle and sender evidence deterministically match an RFQ that is awaiting
  a response or clarification;
- a sender that simultaneously matches customer and supplier authority is
  blocked for manual review;
- ambiguous RFQ correlation, ambiguous customer identity, unknown senders or
  invalid provider provenance stop before AI.

Supplier-response AI has commercial extraction authority only. It cannot select
or change the supplier, RFQ, customer, workflow or RFQ lifecycle state.
Deterministic correlation therefore runs first. Only after correlation succeeds
does the approved privacy transform create the PrivacySafeText supplied to the
production supplier-response parser.

A valid supplier response may record commercial response fields against the
already-correlated RFQ. Duplicate immutable Outlook message identities do not
create a second response. A supplier parser outage stops the bounded pull with
partial_parser_unavailable rather than continuing with uncertain state.

The operator continues to use the existing explicit Outlook pull command.
The returned summary may now additionally contain inbound_route, rfq_id and
correlation_method. Supplier price/body/sender data, Microsoft token material
and raw provider payloads remain excluded from the pull summary. Detailed
commercial review continues through the existing RFQ records.

Attaching a supplier response does not automatically send any customer quote
and does not automatically resume quote progression. Existing human/operator
workflow controls remain required. Supplier RFQ delivery and customer quote
delivery remain manual external operations.

P1-20 introduces no mailbox writes, Mail.ReadWrite, Mail.Send, background
polling, subscription, webhook or autonomous outbound capability.

Implementation regressions for P1-20 are deterministic and offline. Completion
of this code change is not evidence that a live Microsoft tenant/mailbox supplier
reply has been exercised; live pilot tenant validation remains a separate
deployment-readiness activity.

## P1-21 Addendum — Controlled Live Outlook Smoke Validation

P1-21 validates the existing read-only Outlook integration against one
explicitly approved live Microsoft tenant/mailbox. It does not widen the
mailbox permission or outbound authority introduced by P1-19/P1-20.

Do not perform the live smoke while the implementation branch is dirty or
before the P1-21 code has been reviewed, merged, and selected as the approved
pilot release commit.

### Required Environment

The approved pilot host must provide, through the approved secret/deployment
mechanism and not through committed files:

```env
MINAI_PILOT_MODE=true
MINAI_PILOT_BIND_HOST=<approved-loopback-or-private-IP>
MINAI_PILOT_PORT=8000
MINAI_PILOT_ALLOWED_NETWORKS=<approved-private-or-loopback-CIDRs>
MINAI_PILOT_OPERATORS_JSON=<named-operator-secret-map>
MINAI_PILOT_DB_PATH=<approved-pilot-db-path>

MINAI_PILOT_DATA_DIR=<approved-external-pilot-data-pack>

MINAI_OUTLOOK_TENANT_ID=<approved-tenant-uuid>
MINAI_OUTLOOK_CLIENT_ID=<approved-public-client-app-uuid>
MINAI_OUTLOOK_MAILBOX_ID=<approved-pilot-mailbox>
MINAI_OUTLOOK_TOKEN_CACHE_PATH=<approved-external-private-cache-path>

OPENAI_API_KEY=<approved-provider-secret>
```

Do not paste the real values into chat, source code, shell scripts, Git,
receipts, screenshots, or pilot logs.

The configured operational data pack must remain external to the repository
and its required operational datasets must be current `pilot_verified`,
`pilot_usable`, and SHA-256 matched.

### Microsoft Authorization

The Microsoft application remains delegated `Mail.Read` only.

Perform initial or explicit reauthorization on the pilot host:

```bash
python -m src.outlook_auth
```

Sign in only as the mailbox identity configured by
`MINAI_OUTLOOK_MAILBOX_ID`.

Do not grant `Mail.ReadWrite`, `Mail.Send`, application mailbox permissions,
or additional Microsoft Graph scopes for this smoke.

### Prepare Four Controlled Messages

Before the smoke, an authorized operator must prepare exactly one identifiable
inbox message for each scenario:

1. trusted pilot customer sender, no attachment;
2. known supplier sender replying to an RFQ already in
   `awaiting_response`/supported response lifecycle and carrying a deterministic
   RFQ reference;
3. untrusted/wrong supplier sender that must not match customer or supplier
   scope;
4. message with an attachment.

Use controlled test content appropriate for the approved live pilot. Do not use
unnecessary personal or commercial data.

Because the Outlook pull reads newest inbox messages first, keep the four smoke
messages within the selected pull limit and avoid unrelated new inbox traffic
during the two-pass validation window.

### Start the Approved Release

Start only the controlled launcher:

```bash
python -m src.pilot_launcher
```

From the authenticated operator environment:

```bash
python -m src.pilot_operator status
```

The P1-21 runner also verifies the authenticated server startup release through
`/runtime/release`. The server commit must equal the clean local commit used to
run the smoke.

### Pass 1 — Prepare Private Manifest

Choose an absolute external path outside the repository. The destination must
not already exist.

Example:

```bash
python -m src.outlook_live_smoke prepare \
  --manifest /approved/external/evidence/p1-21-outlook-manifest.json \
  --limit 10 \
  --confirm-live-tenant-approved \
  --confirm-openai-data-use-approved \
  --confirm-four-test-messages-prepared \
  --confirm-no-autonomous-outbound
```

This performs one explicit bounded Outlook pull.

The command succeeds only if it can identify exactly one result for each
required scenario.

The manifest contains the four immutable Microsoft Graph message identifiers
and is therefore sensitive operational evidence. It is create-only and must
remain outside the repository. On POSIX systems it is written owner-only.

Do not paste or commit the manifest.

### Pass 2 — Verify Replay and Produce Receipt

Without changing the four source messages or their senders, run the second pass:

```bash
python -m src.outlook_live_smoke run \
  --manifest /approved/external/evidence/p1-21-outlook-manifest.json \
  --receipt /approved/external/evidence/p1-21-outlook-receipt.json \
  --confirm-live-tenant-approved \
  --confirm-openai-data-use-approved \
  --confirm-four-test-messages-prepared \
  --confirm-no-autonomous-outbound
```

The second pull must preserve deterministic routing/idempotency:

- customer message: existing extraction proposal replay;
- supplier message: existing supplier response replay;
- wrong sender: still blocked/manual review;
- attachment message: still blocked/manual review.

The final receipt is create-only and contains only aggregate safe evidence.
It must not contain mailbox identities, sender identities, raw email bodies,
Graph message IDs, proposal IDs, RFQ IDs, Microsoft tokens, OpenAI keys, or
supplier/customer commercial payloads.

A passing result also requires:

```text
mailbox_write_performed = false
automated_send_performed = false
```

### Failure Handling

Stop the live smoke and investigate if any of these occur:

- local worktree is dirty;
- local release and server startup commit differ;
- runtime release identity is unavailable;
- Microsoft authorization is missing or belongs to the wrong mailbox;
- operational data provenance is not verified;
- parser/provider becomes unavailable;
- any required scenario is missing or ambiguous;
- immutable message ID appears with changed sender/body;
- the same immutable message has conflicting prior route history;
- attachment reaches AI;
- mailbox-write or automated-send invariant is not false.

Do not alter the receipt manually to convert a failure into a pass.

### Current Evidence State

The P1-21 implementation and regression suite are deterministic/offline until
the authorized two-pass live command above is executed against the approved
tenant.

Implementation completion alone must not be described as live Outlook pilot
validation.

### P1-21 Manifest Stability Hardening

The private first-pass manifest must not be edited, regenerated, replaced, or
otherwise changed while the second live smoke pass is running.

The runner binds the exact manifest byte snapshot before the Outlook pull and
rechecks its SHA-256 before creating the final receipt.

Any change during execution fails closed and produces no receipt.

## P1-40 Addendum — Controlled Firm Road Live Acceptance Evidence

**Evidence date:** 2026-08-31

This addendum records the first completed controlled live firm-road Email→Quote
acceptance path. It is narrow pilot evidence, not a declaration that every MINAI
transport mode, exception class, pricing policy, or supplier fallback path is
production-ready.

### Accepted Scope

The accepted live scenario was standard road freight with these confirmed facts:

- firm quote mode;
- FTL service;
- Tenteli equipment;
- non-ADR cargo;
- non-temperature-controlled cargo;
- Adana, Türkiye → Hamburg 20095, Almanya;
- 33 Euro pallets, 120 × 80 × 150 cm;
- 20,000 kg gross weight;
- cargo ready date 2026-09-01;
- no customer-requested delivery deadline.

The absent customer delivery deadline did not block pricing. Had the customer
provided a requested deadline, feasibility would have remained mandatory.

### Durable Live Evidence Chain

The completed controlled chain is bound to these durable identifiers:

- extraction proposal: `a130ff25-aa3b-4043-be8c-032ce244ff23`;
- supplier RFQ workflow: `9d0e8f2f-3bd7-48c0-99c5-01e5fea8b8f4`;
- supplier RFQ: `06dbb082-b1e8-45f5-b8db-cc3b52696437`;
- supplier clarification follow-up: `441463e3-14ca-4215-babd-d876f8a906db`;
- customer quote case: `1149a108-c3e3-47c0-8aa2-182496bba217`;
- customer quote approval: `9e13699e-7994-4f5e-aa94-128a3705e5e1`.

### Observed Live Behavior

The supplier first replied with only `2400 EUR`. MINAI preserved that price and
currency without inventing transit, validity, vehicle availability, equipment,
or other commercial facts. Because the firm-road customer quote still required
transit time, MINAI kept the same RFQ and prepared a human-gated clarification
asking only for transit.

After the clarification was manually sent, the supplier replied with only
`5-7 gün`. MINAI consolidated that transit value with the earlier `2400 EUR`
price on the same RFQ, preserving `cost` and `currency` as inherited fields and
retaining both supplier response snapshots in the audit trail.

Quote comparison then contained exactly one current candidate for the RFQ. The
selected supplier quote was `2400 EUR / 5-7 gün`, commercially eligible for a
firm standard-road customer quote.

The controlled pilot's temporary 15% cost-markup assumption produced a customer
price of `2760 EUR`. This value is evidence of the current pilot assumption only;
it is not an accepted production profitability policy. The customer quote was
human-approved and then manually sent with durable send evidence bound to the
exact case, approval and revision.

### Human and Automation Boundaries Proved

The live run proved that:

- supplier RFQ sending required human approval and manual external send evidence;
- supplier clarification required its own human approval and manual send evidence;
- customer quote sending required a current human approval;
- customer delivery was manual and recorded durably;
- Outlook pulls were read-only;
- no supplier or customer email was automatically sent by the pilot runtime.

### Defects Found and Closed During the Live Run

The live run exposed issues that offline regressions had not fully exercised:

- bare price-only supplier replies needed deterministic parsing;
- historical supplier mail needed a temporal correlation boundary;
- supplier clarification drafts needed durable lifecycle and audit evidence;
- clarification human-gate routes needed pilot allowlist access;
- earlier same-RFQ quote snapshots needed to be superseded in comparison by the
  latest response while remaining preserved as evidence.

These fixes reached `main` through PRs #31–#34. The final live acceptance run was
completed on merge commit `cf2b16095f955ee81c10357a98aaacb1176fb11e`.

### What This Evidence Does Not Yet Prove

Separate controlled acceptance is still required for at least:

- supplier terminal response / next-supplier fallback;
- customer inquiries that are missing mandatory firm-pricing information;
- requested-delivery-date feasibility failures;
- agency/customer/quote-specific production pricing policy resolution;
- excluded pilot categories such as ADR, temperature-controlled, oversize and
  non-road freight.

## P1-41 Addendum — Explicit Agency Pricing Configuration

The pilot runtime no longer assumes a 15% customer-price markup. A firm or
indicative customer price requires either a quote override, a verified customer
pricing policy, or an agency default pricing configuration.

The current pilot adapter accepts the agency setting through
`MINAI_AGENCY_PRICING_POLICY_JSON`. The value is configuration, not a secret, but
it should still be controlled as commercial policy. Example schema:

```json
{
  "default_formula": {
    "method": "cost_markup_percentage",
    "value": 12.5
  },
  "default_rounding": {
    "mode": "none"
  },
  "currency_rounding": {
    "EUR": {
      "mode": "up",
      "increment": 10
    }
  }
}
```

Do not copy the regression suite's synthetic 15% fixture into a live agency
configuration unless the agency has explicitly adopted that policy.

A one-quote override can be supplied by the authenticated operator command:

```text
workflow resume-quote <workflow-id> \
  --pricing-method fixed_profit \
  --pricing-value 300
```

Both override arguments are required together. If the policy is missing or
malformed, the workflow fails closed at `pricing_policy_required` and does not
create a customer quote case.

## P1-42 Addendum — Supplier Initial Dispatch Policy

P1-42 separates supplier ranking from the number of suppliers contacted in the first RFQ batch. The controlled pilot accepts the optional agency configuration through `MINAI_SUPPLIER_DISPATCH_POLICY_JSON`.

Backward-compatible default when the setting is absent:

```json
{"mode":"sequential","initial_supplier_count":1}
```

Example parallel configuration:

```json
{"mode":"parallel","initial_supplier_count":2}
```

Supported P1-42 modes are `sequential` and `parallel`. Parallel mode may create RFQ drafts for the first two or three eligible ranked suppliers, but each RFQ still requires the normal human approval and explicit send step. No supplier email is sent merely because a parallel policy is configured.

The policy is copied into the durable supplier RFQ workflow when that workflow is created. Do not describe hybrid timeout dispatch as implemented in P1-42; response-time thresholds and scheduled fallback batches remain a later controlled change intended for the Supplier Dispatch Policy section of the future guide/editor.


## P1-55 controlled attachment retrieval smoke

P1-55 is a read-only verification boundary, not an attachment parsing feature. A live smoke is valid only when an attachment is already `metadata_allowlisted`. MINAI must first resolve a single trusted customer or supplier route; untrusted or ambiguous attachment messages must show no content download.

For a trusted allowlisted attachment, expect `attachment_retrieval_status=verified`, `attachment_content_download_performed=true`, a nonzero `attachment_verified_count`, `mailbox_write_performed=false` and `automated_send_performed=false`. The top-level result must remain `inbound_mail_manual_review_required`; no customer or supplier AI parser is authorized by P1-55. Operator output must not contain raw attachment content, provider attachment IDs or SHA-256 file fingerprints.


## P1-56 safe attachment extraction smoke

P1-56 extends the trusted-route P1-55 retrieval boundary with deterministic, bounded extraction. It does not authorize attachment interpretation by AI. The controlled pilot runtime now requires the exact locked `pypdf` version in `requirements-lock.txt`; run `python -m src.runtime_preflight` after installing the lock before deployment.

For a trusted PDF/XLSX/CSV attachment that passes P1-54 and P1-55, expect `attachment_extraction_status=extracted`, `attachment_extracted_count` greater than zero and bounded aggregate character/table counts. The top-level result must remain `inbound_mail_manual_review_required` with `reason_code=outlook_attachment_content_extracted_not_interpreted`. The operator summary must not contain extracted PDF text, spreadsheet/CSV cell values, provider attachment IDs, raw attachment bytes or file hashes.

Encrypted/no-text PDFs, formula-bearing XLSX files, malformed content or any extraction limit breach must fail closed to manual review. Untrusted/ambiguous routes must still show no attachment content retrieval and therefore no extraction. P1-56 adds no mailbox writes, no automated send and no customer/supplier AI attachment parsing.

## P1-57 controlled attachment interpretation boundary

P1-57 adds a non-authoritative AI interpretation step after successful P1-56 extraction. It does not authorize automatic application of attachment facts. A trusted attachment must still pass metadata allowlisting, route verification, transient content validation and bounded extraction before interpretation is considered.

The interpretation input is built from system-labeled email subject/body and extracted attachment sections. Each source section passes the approved privacy minimization before the route-specific parser sees it. The combined input is bounded to 120,000 characters before privacy processing; overflow fails closed without truncation. Customer interpretation returns only an internal ShipmentProposalSnapshot candidate. Supplier interpretation returns only an internal SupplierResponseExtraction candidate. P1-57 does not save a customer proposal, attach a supplier response, advance RFQ state, write the mailbox or send any email.

For operator pull, expect `attachment_interpretation_status=interpreted`, `attachment_interpretation_parser_called=true` and a safe interpretation reason when a controlled interpretation succeeds. The top-level message remains `inbound_mail_manual_review_required`. Operator output must not contain extracted attachment content, interpreted structured payloads, attachment provider IDs or file hashes. A live AI smoke must use an explicitly approved, controlled non-sensitive attachment (or separate explicit approval for the specific attachment content); prior extraction-only test files are not automatically authorized for AI interpretation.

P1-57 is OFF by default. Use the explicit one-pull opt-in only for approved test/operational content:

```bash
python -m src.pilot_operator outlook pull --limit 10 --interpret-attachments
```

Omitting `--interpret-attachments` keeps the pull at the P1-56 extraction-only boundary and must report `attachment_interpretation_requested=false` at the pull level.

## P1-58 attachment interpretation review and apply

P1-58 turns a successful opt-in P1-57 interpretation into a durable review case. Run the existing explicit interpretation pull:

```bash
python -m src.pilot_operator outlook pull --limit 10 --interpret-attachments
```

A successfully reviewed attachment candidate should remain `inbound_mail_manual_review_required` and return an `attachment_review_id`, `attachment_review_status=pending`, and a nonzero pull-level `attachment_review_count`. The pull summary must not contain the interpreted candidate, attachment hashes or extracted source content.

List and inspect pending reviews through the authenticated operator surface:

```bash
python -m src.pilot_operator attachment-review list
python -m src.pilot_operator attachment-review get <review_id>
```

Apply only after inspecting the candidate. Optional corrections use the same JSON object pattern as other controlled operator corrections:

```bash
python -m src.pilot_operator attachment-review apply <review_id> --corrections '{}'
```

For a customer review, apply creates a traceable but still-unconfirmed extraction proposal. Continue with the normal `proposal get`, `proposal confirm`, and only then `proposal resume` steps. P1-58 apply itself must not enter the operational pipeline.

For a supplier review, apply is allowed only while the Supplier RFQ still matches the exact review-time snapshot. A stale RFQ must return a lifecycle conflict and leave the review pending. A successful supplier apply creates the RFQ response and uses the normal supplier response lifecycle transition; it does not send any email.

Reject an interpretation that should not be applied:

```bash
python -m src.pilot_operator attachment-review reject <review_id> --reason "Needs manual verification"
```

Applied/rejected reviews are terminal. All P1-58 paths retain `mailbox_write_performed=false` and `automated_send_performed=false` for Outlook pull; review apply/reject themselves contain no outbound mail operation.

## P1-59 field-level attachment review preview

Before applying a pending attachment review, inspect its authenticated detail and generate a preview with the intended corrections. The preview is mutation-free and returns field categories, original/preview values, changed fields, attention reasons, blockers/warnings, aggregate counts and a `preview_token`.

```bash
python -m src.pilot_operator attachment-review get <review-id>
python -m src.pilot_operator attachment-review preview <review-id> --corrections '{"is_high_value":false}'
```

Apply requires the exact preview token returned for those corrections:

```bash
python -m src.pilot_operator attachment-review apply <review-id> --corrections '{"is_high_value":false}' --preview-token <token>
```

If review state or corrections differ, apply must fail closed. Preview does not create a customer proposal, supplier response, mailbox write or outbound send. For customer reviews, safety-critical unknown/changed fields require explicit operator attention but the later extraction-confirmation gate remains authoritative. For supplier reviews, non-applyable quote state or unresolved critical commercial fields appears as a blocker before mutation.

## P1-60 attachment review operational queue

Use the authenticated read-only queue to decide which pending attachment review should be inspected first:

```bash
python -m src.pilot_operator attachment-review queue
```

The queue returns only pending review IDs plus route, age, priority band/score, reason codes, aggregate attention/blocker/warning counts and relative nearest-deadline information. It does not expose customer identity, subject, candidate values, preview tokens or attachment/source fingerprints.

Priority is deterministic and recalculated on every read. `critical` items include combinations of unresolved safety/commercial attention, near/past exact ISO dates, or stale/missing Supplier RFQ snapshots. Free-form date text is not interpreted for priority. A high queue priority does not authorize apply: continue with `attachment-review get`, `attachment-review preview`, and only then `attachment-review apply` using the matching P1-59 preview token.

## P1-61 unified operational work queue

Use the authenticated read-only inbox to see human work across the supported pilot workflows:

```bash
python -m src.pilot_operator work queue
```

The queue includes only current human-action items: pending attachment reviews, proposed customer extraction confirmations, Supplier RFQ follow-up drafts/approved follow-ups, clarification-required RFQs with no active follow-up, and pending quote approvals. Supplier follow-ups already awaiting a supplier response and completed/rejected/applied work are excluded.

Use each item's `resource_type`, `resource_id` and `next_action` only to navigate to the existing controlled workflow. Attachment work continues through `attachment-review get/preview/apply|reject`; customer extraction through `proposal get/confirm/resume`; supplier follow-up through the existing `rfq follow-up-*` commands; quote approvals through `approval get/approve|reject`. A `supplier_clarification_gap` requires inspection of the referenced RFQ and is never auto-repaired by the queue.

Priority is recalculated on read from age, current safety/commercial attention, lifecycle consistency and strict ISO operational dates. Free-form dates are not interpreted. The queue is mutation-free and must not expose party identity, subject/body text, candidate values, prices/currency, clarification text, preview tokens or attachment/source fingerprints.

If `next_action` is an inspection action such as `inspect_supplier_follow_up` or `inspect_quote_approval_state`, do not proceed directly to send/approve. Inspect the referenced resource with its existing GET command first; the inbox detected a durable state inconsistency that must be resolved through the underlying workflow, not through queue mutation.

## P1-62 operational work item detail and recovery

Start with the unified inbox, then inspect one current work item by its `work_id`:

```bash
python -m src.pilot_operator work queue
python -m src.pilot_operator work get <work-id>
```

The detail explains `why_waiting`, separates `blocking_reasons`, exposes privacy-minimal state checks and returns structured `operator_commands` using existing controlled CLI actions. The command argv is guidance only; it does not execute anything and does not grant authority.

If a work item has disappeared since the queue read, `work get` returns not found. Refresh the queue instead of acting on a stale ID. Inconsistent supplier follow-up or quote-approval state returns inspection-only recovery. A supplier clarification gap may recommend the existing `workflow resume-quote` path only while the RFQ is still clarification-required, no active follow-up exists and the workflow is present.

## P1-63 operational work assignment and acknowledgement

Assignment is optional coordination metadata for the unified operational inbox; it is not permission to perform the underlying action. Start from the current queue/detail, then claim an item only when you intend to handle it:

```bash
python -m src.pilot_operator work queue
python -m src.pilot_operator work get <work-id>
python -m src.pilot_operator work assign <work-id>
python -m src.pilot_operator work ack <work-id>
```

`work assign` records the authenticated token owner. If another operator already owns the same current work state, the command returns a lifecycle conflict; refresh `work queue`/`work get` rather than duplicating work. `work ack` records that the assigned operator has actively acknowledged the task. Assignment and acknowledgement do not change priority or execute any recovery command.

When you stop handling an active item without completing its underlying workflow, release it:

```bash
python -m src.pilot_operator work release <work-id>
```

Only the current assignee may acknowledge or release. If the underlying work state changes, the old assignment becomes stale automatically and a fresh claim is required for the new state. A resolved/stale work ID cannot be newly assigned. Continue to use the existing `proposal`, `attachment-review`, `rfq`, `workflow`, `approval` and `case` commands; their existing lifecycle/authentication/preview/send guards remain authoritative and do not depend on assignment ownership.

## P1-64 operational work assignment lease and stale-operator recovery

P1-63 assignments are now bounded coordination leases. A new assignment lasts 30 minutes. A first acknowledgement refreshes that lease; thereafter renew it explicitly only while you are still actively handling the same current work state:

```bash
python -m src.pilot_operator work assign <work-id>
python -m src.pilot_operator work ack <work-id>
python -m src.pilot_operator work renew <work-id>
```

`work renew` is accepted only from the authenticated current assignee and only before lease expiry. There is no automatic heartbeat. Queue/detail show privacy-minimal lease status and remaining/expiry information; lease metadata never replaces the underlying workflow checks.

If the lease expires, refresh `work queue` / `work get`. Normal assign, ack and renew will remain blocked for that expired current assignment. Recover explicitly:

```bash
python -m src.pilot_operator work takeover <work-id>
```

Takeover is permitted only after expiry and only if the same work item/state is still current. It creates a new assignment generation. If the underlying work state changed or disappeared, use the current queue and normal assign path instead. Never use takeover as a shortcut around proposal confirmation, quote approval, attachment preview/apply, supplier lifecycle or outbound send guards.

P1-63 records created before lease support and lacking `lease_expires_at` are treated as expired, not permanently owned. Released records remain audit history. Assignment priority remains unchanged by lease, renewal or takeover.

## P1-65 authenticated My Work and shift handoff

Use the personal read-only view when starting or resuming an operator shift:

```bash
python -m src.pilot_operator work mine
```

The view is scoped by the authenticated pilot identity and lists only your current lease-active `assigned` / `acknowledged` work. It sorts shorter remaining leases first. `lease_attention=expiring_soon` means five minutes or less remain; renew only if you are still actively handling that same work state. Expired assignments do not remain in My Work; use the normal queue/detail and P1-64 takeover recovery when appropriate.

When ending a shift or intentionally returning an unfinished active item to the shared queue, use:

```bash
python -m src.pilot_operator work handoff <work-id>
```

Handoff records an audited `shift_handoff` release and leaves the item unassigned. It does not select or authorize the next operator and carries no free-form handoff note. The receiving operator must refresh `work queue` / `work get` and claim the item with `work assign`. Handoff never performs the underlying proposal, attachment-review, RFQ, workflow, approval or send action.

## P1-66 shift summary and handoff readout

Use the authenticated shift summary near the end/start of a shift or before deciding what coordination work needs attention:

```bash
python -m src.pilot_operator work shift-summary
```

The summary combines four privacy-minimal views: your current lease-active My Work items, your `expiring_soon` count, your own recent shift handoffs from the last 12 hours (maximum 20), and currently critical unassigned work. A handoff may show whether the same work state is now unassigned, claimed, expired, changed or no longer active.

The command is GET-only. It never renews a lease, assigns work, performs a handoff, takes over expired work or executes any proposal/RFQ/approval/attachment action. Use `work mine`, `work get`, `work assign`, `work renew`, `work takeover`, `work handoff` and the underlying controlled workflow commands separately as appropriate. Do not treat a shift-summary item as authorization for the underlying action.

## P1-67 shift close readiness and handoff completeness

Before ending an operator shift, run the read-only readiness gate:

```bash
python -m src.pilot_operator work close-readiness
```

`ready_to_close=true` means coordination coverage is currently clear: you hold no active assignment, you have no same-state expired assignment that still needs cleanup, your recent handoffs are either claimed or no longer active, and there is no critical unassigned work in the shared queue. The command does not actually close a shift and creates no durable close record.

If `active_assignments_remaining` is present, finish the controlled workflow or use `work handoff` / `work release` as appropriate. If `expired_assignments_require_recovery` is present, refresh with `work get`; use the existing P1-64 recovery path such as `work takeover` when needed before a handoff, or release the assignment when intentionally returning it. If `recent_handoffs_incomplete` is present, the receiving shift must refresh current state and claim appropriate work through normal `work assign`. If `critical_unassigned_work_requires_coverage` is present, the critical item must be inspected and deliberately claimed by an operator before readiness can pass.

`active_assignment_lease_expiring_soon` is a warning layered on top of the active-work blocker. Readiness never performs assignment or workflow mutations and does not authorize any proposal, attachment, supplier, approval, case or send action. Always use the existing controlled commands and lifecycle guards for the actual work.

## P1-68 shift close attestation and evidence receipts

First recheck current readiness:

```bash
python -m src.pilot_operator work close-readiness
```

Only when that current readout is ready, explicitly attest the close state:

```bash
python -m src.pilot_operator work close-attest
```

The server recomputes readiness again inside the same SQLite transaction that records the receipt. If coverage changed between the read and attestation, attestation fails with a lifecycle conflict and no receipt is written. Repeating attestation against the exact same unchanged state is idempotent.

Review your own recent receipts with:

```bash
python -m src.pilot_operator work close-receipts
```

`current` means the receipt still matches a freshly recomputed ready close state. `stale` means queue, assignment, lease, handoff or readiness state changed; the receipt remains historical evidence only. Never use a receipt as authorization for assignment, proposal confirmation, attachment apply, RFQ/quote approval, workflow resume or outbound send.

Receipt status is non-resurrecting: after any later operational persistence event, an older receipt remains historical/stale even if the visible queue later happens to return to the same shape. Always use current `work close-readiness` plus a fresh `work close-attest` for the new close state.

### P1-69 — Shift Open / Incoming Shift Reconciliation

At the beginning of a shift, run `python -m src.pilot_operator work open-reconciliation` after operator authentication. This is a read-only reconciliation surface; it does not open a durable shift or claim any work.

Review the latest prior shift-close evidence, safe post-close change category counts, incomplete recent handoffs and current critical uncovered work. `review_required=true` means the incoming operator must inspect current work using existing `work queue` / `work get` and claim coverage only through normal `work assign` when appropriate.

A missing or stale close receipt is not repaired automatically. Receipt history is evidence only. Cross-operator handoff records intentionally omit operator identity, and post-close change summaries never return raw event payloads, entity IDs or internal event types.

### P1-70 — Incoming Shift Acceptance Evidence

At shift start, first run `python -m src.pilot_operator work open-reconciliation`. Only when the current response is `reconciliation_status=clear` and `review_required=false` should the incoming operator explicitly record acceptance with `python -m src.pilot_operator work open-accept`.

The POST recomputes reconciliation inside the same SQLite transaction that writes evidence. If state changed after the read, the command fails with a lifecycle conflict and writes no receipt. Repeating acceptance for the exact same authenticated operator and unchanged state is idempotent.

Review your own recent acceptance evidence with `python -m src.pilot_operator work open-acceptances`. `current` means it still matches a fresh clear reconciliation; `stale` means continuity changed. An acceptance receipt never claims work or authorizes workflow actions. Use `work queue`, `work get` and normal `work assign` for actual coverage.

### P1-71 — Shift Continuity Audit / Cycle Ledger

Use `python -m src.pilot_operator work continuity` to inspect retained organization-level close/open continuity evidence. The command is read-only and does not depend on the requesting operator owning any work.

Read `completion_status` and `evidence_freshness` separately. `complete` means an incoming acceptance was recorded for the cycle; later normal work may make that evidence `stale` without creating a historical gap. `open` means the newest close still awaits acceptance. `gap` means an older close was superseded without acceptance and should remain visible as audit attention.

Duplicate close attestations against one unchanged operational high-water state are grouped as one cycle until an acceptance occurs. Operator identities and acceptance receipt IDs are intentionally omitted. Use the existing `open-reconciliation` and `open-accept` paths for current incoming-shift handling; never treat the ledger as authority to repair, claim, transfer or approve work.

### P1-72 — Primary Supplier Dispatch and Response Timing

Use `python -m src.pilot_operator workflow dispatch-status <workflow_id>` to inspect each supplier's current dispatch tier, acknowledgement state, reminder due time and next controlled action. `primary` and selected `specialist` suppliers form the protected first group; `backup` suppliers are held as secondary.

If a supplier confirms by phone or WhatsApp that the RFQ was seen, record only that fact with `python -m src.pilot_operator rfq ack-seen <rfq_id> --channel phone|whatsapp`. This is not a quote and does not close the RFQ. The road grace timer then runs for 120 minutes from the acknowledgement. Email replies such as “mailinizi aldık, çalışıyoruz” are ingested as the same non-commercial acknowledgement state.

A silent supplier reaches `send_no_response_reminder` after 30 minutes from confirmed send. The dispatch status also indicates that continued silence after the reminder requires human phone/WhatsApp escalation. Do not interpret silence as no capacity and do not release backup suppliers for customer urgency alone.

Secondary supplier approval remains blocked until all primaries explicitly report `no_capacity`/`declined`, or until every primary has a terminal result and the operator has completed real price negotiation. For the latter case, record only the fact that negotiation was exhausted with `python -m src.pilot_operator workflow secondary-release <workflow_id>`. Never enter the customer's raw target price into that command or supplier communications.

The policy carries a five-minute proactive customer-deadline update lead, but P1-72 intentionally does not infer a quote-response deadline from delivery dates or free-text urgency. A later structured customer-deadline step must provide the actual deadline before MINAI can automate that customer status message safely.

## P1-73 — Automatic Follow-Up, Customer Quote Deadline, and Business Hours

Default pilot business hours are Monday-Friday 09:00-18:30 in Europe/Istanbul. Supplier reminder timers count business minutes only. A Friday 18:20 silent RFQ reaches its 30-minute reminder on Monday 09:20; a Friday 17:30 acknowledgement reaches its 120-minute reminder on Monday 10:00.

Automatic supplier reminders and customer deadline updates are independently disableable through the supplier dispatch policy. Outside business hours the scheduler does not send automatic mail and does not surface phone/WhatsApp escalation work. Inbound mail may still be ingested; state is rechecked before the next business-time action.

Explicit customer quote deadlines are distinct from required delivery dates. A deadline after business close moves the single proactive status update to five minutes before close when that safe window still exists. Urgency alone does not create a deadline. Provider failure is not automatically retried.

Approved initial supplier RFQ and controlled supplier follow-up provider sends are rejected before provider delivery outside business hours. This does not grant automatic initial RFQ authority: approved drafts remain under the existing controlled send workflow. `/automation/status` is authenticated/read-only and reports scheduler health plus the active business calendar.
## P1-74 Supplier calendar and customer deadline separation

Supplier automation uses a fixed Turkey communication calendar: Europe/Istanbul, Monday-Friday, 09:00-18:30. This is not a Guide Editor setting. Turkish full public holidays close the supplier day; statutory half-day eves close at 13:00. Verified religious-holiday coverage is reported by `/automation/status`.

Customer quote-deadline updates are independent of supplier hours. An explicit customer deadline keeps its own clock and default five-minute lead, including evenings/weekends. If no usable supplier price exists, a 20:00 customer deadline is eligible for the one proactive update at 19:55 while supplier outbound remains paused.

If the current supplier calendar year is not verified, supplier timed automation fails closed and requires calendar maintenance. Do not bypass this by changing agency dispatch policy. Foreign country/region holiday calendars are deferred to future import workflows.


## P1-75 — MINA Job / Case Model

A genuine customer inquiry receives its MINA code only when an authenticated operator confirms the extraction proposal. The confirmation response contains `mina_job_id` and `mina_code`; the first new confirmed job in 2026 is expected to be `MINA2026/1` when no earlier P1-75 job exists. Do not pre-create MINA codes for proposed/spam intake.

Use the authenticated `GET /mina-jobs` surface for the job list and `GET /mina-jobs/{job_id}` for one job's current lifecycle, supplier status, reminder plan, quote/revision summary, automation state and durable timeline. The slash-bearing human code is display/reference data; API routing uses the opaque `job_id`.
Job-specific automation override changes are controlled POST actions and are intended for the future job-detail UI. Disabling supplier reminders converts due automation into manual operational work for that MINA job; it does not alter agency defaults or other jobs. Closed jobs reject override changes.

For an individual supplier RFQ inside a MINA job, use the reminder-preview endpoint before an optional early send. Preview is read-only and returns the subject/body plus planned due time and whether supplier communication is currently open. The send-now endpoint requires authenticated operator authority and still enforces supplier hours/holidays. A successful early reminder consumes the same durable scheduler action, preventing later duplicate delivery.

Lifecycle transitions are explicit controlled mutations. Delivery normally closes the operation. Lost or cancelled closure requires a reason. P1-75 does not yet provide the graphical main job screen; P1-76 will consume these backend list/detail/action contracts. MINA job/timeline state is intentionally retained beyond the standard 30-day pilot state purge, while raw mail and ordinary pilot state retain their existing privacy/retention rules.

## P1-76 — MINA Operations Development UI

The optional Streamlit development UI now opens on `MINA İşleri`. It lists durable MINA jobs and provides job detail tabs for general status, suppliers, quote summary, timeline and controlled job actions. `Yeni Talep` preserves the existing manual email-development flow and `Veri & Rehber` contains the existing data/customer-memory tooling.

The job controls mirror P1-75 APIs: job-wide automation disable overrides, supplier reminder preview/early send and valid manual lifecycle transitions. Early reminder send has no extra confirmation dialog, but backend supplier-hours and duplicate-send guards remain mandatory.
P1-76 does not approve Streamlit for live pilot use. Do not inject pilot bearer credentials into the Streamlit source or treat the development UI as an authenticated pilot boundary. Live pilot authority remains the authenticated FastAPI/operator-client surface until a browser/session security layer is separately approved.

For development UI validation use `python -m py_compile ui/app.py ui/mina_operations.py` and `python -m src.simulation.mina_operations_ui_regressions`. The controlled pilot launcher remains unchanged and does not start Streamlit.

## P2-16.4 Persistence and Housekeeping Superseding Note

For every real controlled-pilot launch after P2-16.4, earlier examples that place `MINAI_PILOT_DB_PATH` under `data/pilot/` are superseded. Use an approved absolute external path, for example an access-controlled deployment data directory outside the repository. Pilot startup fails closed when the path is missing, relative, or resolves inside the repository.

The repository-owned `data/pilot/minai_pilot.sqlite3` default remains a development/synthetic compatibility path only when pilot mode is disabled. Do not copy a real pilot database or its WAL/SHM files into the repository for backup, debugging, transfer, or evidence review. Use the approved external backup/evidence process instead.

Ordinary transient state and audit evidence retain the configured deletion window (30 days by default). Operational continuity records that must remain linked across longer jobs, assignment generations, shift handoffs, commercial/master authority, exceptions and learning review are excluded from the ordinary purge; this is a technical continuity class, not permission to retain raw mail indefinitely.

State rows created before P2-16.4 remain readable as legacy storage schema v0. New and refreshed rows use schema v1; unknown future versions stop rather than guessing. New quote/RFQ/response workflow timestamps are timezone-aware UTC. Existing legacy naive timestamps are compatibility input only.

## P2-16.5 Deployment Profile Isolation

Do not start the primary web shadow pilot by sourcing both the primary pilot env and a smoke/local pilot env into the same process. The later file can silently replace `MINAI_PILOT_DB_PATH`, `MINAI_PILOT_DATA_DIR`, mailbox identity or other runtime authority.

Validate the primary profile without starting the server:

```bash
python -m src.pilot_profile_launcher \
  --core-env ~/.config/minai/pilot.env \
  --overlay-env ~/.config/minai/web-pilot.env \
  --check-only
```

For a separate Outlook smoke profile, use the smoke env as the core profile rather than as an overlay:

```bash
python -m src.pilot_profile_launcher \
  --core-env ~/.config/minai/local-pilot.env \
  --overlay-env ~/.config/minai/web-pilot.env \
  --check-only
```

After the check-only result identifies the intended DB path, data-pack root and `outbound_mode=shadow`, remove `--check-only` to launch. The profile env files themselves must be absolute/external at runtime; shell `~` expansion in the command above produces the required absolute path before Python receives it.

## P2-16.6 — Pre-Pilot Hardening

Before connecting a real agency mailbox, validate the controlled-pilot profile with `python -m src.pilot_profile_launcher --core-env <pilot.env> --overlay-env <web-pilot.env> --check-only`. Parent-shell `MINAI_*`, Outlook, OpenAI, operator and provider settings are not deployment authority; put every required application setting in the selected core profile.

The preflight now requires a fully verified external pilot data pack. `customer_memory.json` and `supplier_capabilities.json` must satisfy the pilot-pack cardinality/structure rules, carry human-reviewed `pilot_verified` provenance and match their recorded SHA-256 fingerprints. Editing either dataset after verification intentionally makes the pack unstartable; create and review a new pack version instead of weakening the check.

For the first real agency shadow phase keep `MINAI_OUTBOUND_MODE=shadow`. Authenticate Outlook in that profile only after confirming the displayed delegated permission is `Mail.Read`. The CLI reports the actual scopes cached for the selected profile. Do not grant `Mail.Send` for historical analysis or shadow observation. `Mail.Send` is reserved for the later separately approved `controlled_send` phase.

Shadow safety does not depend only on using the launcher. A direct FastAPI pilot startup runs the same controlled-runtime preflight, and default/non-pilot runtime no longer enables outbound delivery implicitly. At the Graph boundary, a read-only Outlook configuration is rejected before token acquisition/provider POST even if a caller reaches the send client unexpectedly. Conversely, selecting `controlled_send` without a valid Outlook sender configuration or usable cached `Mail.Send` authorization blocks pilot startup instead of launching a scheduler with no provider. A malformed `MINAI_PILOT_MODE` also blocks direct ASGI startup. Pilot legacy-bootstrap reads each dataset once, verifies the fingerprint against those exact bytes, and imports those same bytes, so post-startup or concurrent tampering cannot be imported into Master Data.

Ordinary retention may still delete unrelated transient state, but it must not sever a retained MINA job from extraction/message-idempotency evidence, RFQ lifecycle/send evidence, quote approval/case state, relevant attachment review or scheduled automation state. Replaying an old provider message after retention must resolve to its existing durable evidence instead of creating a fresh proposal. This continuity rule does not permit durable raw email-body or attachment-content storage.

Release gate for this milestone: targeted P2-16.6 regressions, source compilation, `git diff --check`, the canonical pilot regression suite, then the exact-head Controlled Pilot Gate. A real mailbox remains blocked until all gates pass and the user separately authorizes the real-agency cutover.

## P2-17 — Read-Only Counterparty Discovery Before Agency Pack Creation

Use this step only for a newly authorized agency mailbox that does not yet have verified Customer/Supplier Master Data. It intentionally runs outside the controlled-pilot app, so an empty agency data pack does not need to be weakened or temporarily replaced with smoke data.

Create a dedicated external auth profile, for example `~/.config/minai/agency-outlook-readonly.env`, containing only `MINAI_OUTLOOK_TENANT_ID`, `MINAI_OUTLOOK_CLIENT_ID`, `MINAI_OUTLOOK_MAILBOX_ID`, and `MINAI_OUTLOOK_TOKEN_CACHE_PATH`. Do not add `MINAI_OUTBOUND_MODE`, OpenAI keys, DB/data-pack settings or operator credentials. Keep the token-cache path external and owner-only.

Validate the profile without authenticating or reading mail:

```bash
python -m src.outlook_counterparty_discovery check \
  --auth-env /absolute/path/to/agency-outlook-readonly.env
```

The check must report `permissions=["Mail.ReadBasic"]` and `outbound_mode=shadow`. Then run the interactive device authorization with the same profile:

```bash
python -m src.outlook_counterparty_discovery auth \
  --auth-env /absolute/path/to/agency-outlook-readonly.env
```
After the operator confirms that Microsoft is granting `Mail.ReadBasic` access to the intended mailbox, run bounded discovery. Use the actual authorized history window; the hard maximum is 370 days and 10,000 examined messages. Inbox and Sent Items receive separate quotas, newest messages are examined first, and the result reports per-folder examined/accepted counts plus truncation status.

```bash
python -m src.outlook_counterparty_discovery discover \
  --auth-env /absolute/path/to/agency-outlook-readonly.env \
  --start-at 2025-09-08T00:00:00+03:00 \
  --end-at 2026-09-08T00:00:00+03:00 \
  --max-messages 10000 \
  --authorization-confirmed
```

Add `--agency-alias address@example.com` for each legitimate agency alias that can appear as sender/recipient. Discovery does not request message subjects, bodies or attachments and does not call AI. Output is transient candidate identity/traffic evidence; avoid redirecting it into long-lived files unless an approved onboarding evidence policy explicitly requires that storage.

Review the highest-traffic unmatched addresses/domains with the agency operator. Humanly classify the desired initial scope as 2–3 pilot customers and 3–5 road suppliers, confirm the correct operational email contacts, and then enter them through the normal Master Data/data-pack intake. Only after the resulting agency pack is human-reviewed, fingerprint-current and `verified=true` should the controlled shadow-pilot profile be pointed at it.

Once deterministic customer/supplier identities exist, run the existing historical relationship onboarding to derive proposed timing/communication/behavior facts. Counterparty discovery itself never creates those facts and never treats traffic volume as evidence that an address is a customer or supplier.

## Air Freight Shadow — Commercial-Air Tariff PDF Registration

The controlled pilot may register commercial-air tariff PDFs from **Ayarlar → Havayolu Listeleri**. The operator supplies the airline, optional cargo scope/origin-airport/validity metadata and the original PDF. Only PDF files up to 10 MiB are accepted. Registration stores the exact verified artifact in protected deployment-owned storage and displays it as `registered_not_interpreted`.

A successful upload is not an air-pricing readiness signal. Until a later interpretation/review step is implemented, MINAI must not derive rates, surcharges, chargeable weight, pivot weight, capacity, schedules or customer prices from the document. Express/FedEx/Aramex tariffs are intentionally not accepted by this surface.

## Commercial-Air Tariff Structure Review (P2-19)

After a commercial-air PDF is registered under **Ayarlar → Havayolu Listeleri**, an authenticated operator may choose **Yapıyı Çıkar**. MINAI reads the protected PDF locally, applies the existing bounded PDF text extractor and proposes only structural labels such as weight breaks, surcharge names, currency, volumetric divisor and cargo-scope hints. No OpenAI parser is called in this phase and the full extracted text is not persisted in the pilot database/audit payload.

Review each proposed label individually. **Doğrula** and **Reddet** both require an operator note. A confirmed label means only “this label exists/is correctly recognized in this tariff source”; it does not authorize a rate, surcharge amount, chargeable-weight formula, pivot-weight choice, airline quote, capacity assumption, booking or customer quote. Numeric tariff-row interpretation remains outside the controlled pilot boundary until a later separately approved implementation and applicable OpenAI data-control approval.

If extraction returns an encrypted/no-text/malformed/oversized-page or character-limit error, treat the document as manual-review-only; do not bypass the extractor and do not paste commercial tariff contents into another AI surface as a workaround.

## Commercial-Air Tariff Row Review (P2-20)

After every structural candidate for a tariff PDF has been explicitly reviewed, **Ayarlar → Havayolu Listeleri** may show **Tarife Satırlarını Çıkar**. MINAI locally re-extracts the protected PDF, verifies that the extracted-text fingerprint is unchanged, and looks only for exact-width numeric rows beneath human-confirmed weight-break headers. It does not call OpenAI.

Review every proposed destination row against the original PDF. **Satırı Doğrula** and **Satırı Reddet** both require an operator-authored note. If any destination, currency, column alignment or numeric value is uncertain, reject the row; do not repair it by assumption. The v1 detector deliberately prefers missing rows to guessed rows.

A confirmed row is only a checked transcription/reference record. It is not used for chargeable-weight or pivot-weight calculations, surcharge computation, customer pricing, airline selection, space/schedule requests, booking or outbound messages. Those capabilities remain disabled until a separately approved air-pricing phase. Express tariffs remain out of scope.

## Commercial-Air Freight Calculation Preview (P2-21)

After a tariff row is explicitly confirmed under **Ayarlar → Havayolu Listeleri**, use **Navlun Önizleme** only as a shadow/reference calculation. Enter actual weight and volumetric weight; MINAI displays raw chargeable weight, every available `+N` alternative and whether a higher booked weight is the cheapest base-freight pivot.

The preview deliberately excludes all surcharges/local charges, airline capacity, schedule/routing, customer margin and customer quote generation. It also applies no airline kg rounding because that rule has not yet been evidenced. A displayed pivot therefore remains a calculation aid, not a bookable or customer-facing offer.

The backend can also derive volumetric weight from explicit total volume when the tariff's structure review contains exactly one confirmed divisor. Never bypass a missing/conflicting divisor by assuming `/6000`; confirm the source evidence first.

## Commercial-Air Surcharge Amount Review (P2-22)

After the tariff structure review is fully completed, **Ayarlar → Havayolu Listeleri** may show **Surcharge Tutarlarını Çıkar** when at least one surcharge label was human-confirmed. MINAI reuses the protected PDF and the already verified extracted-text fingerprint; it only inspects the line numbers attached to those confirmed surcharge labels.

V1 creates a proposal only when the line contains an explicit amount, currency and supported unit such as `USD 0.50 / KG` or `EUR 25 / SHIPMENT`. Unitless entries, percentage charges, multiple amounts on one line and unsupported formulas remain manual-review-only. Do not convert a skipped line manually into a calculated rule merely to make the preview complete.

**Surcharge Doğrula** confirms transcription only. In particular, `/kg` does not yet tell MINAI whether the airline applies the charge to physical, chargeable or pivot/booked weight. Confirmed surcharge records are therefore not included in the current **Navlun Önizleme**. Do not treat them as customer-pricing readiness, capacity/schedule evidence or booking authority.

## Commercial-Air Surcharge Application-Basis Review (P2-23)

After a surcharge amount/currency/unit candidate is confirmed under **Ayarlar → Havayolu Listeleri**, review its application basis separately. For a `/kg` candidate choose only the basis directly supported by the source or known operational evidence: **Gerçek ağırlık**, **Chargeable weight**, or **Pivot sonucu billed weight**. For a flat candidate confirm only **Sabit / shipment-AWB**. Every choice requires an operator note.

Do not choose chargeable weight merely because the surcharge says `/kg`, and do not infer shipment versus AWB quantity scope from the flat selector. The UI explicitly keeps calculation consumption off. If the source does not support the basis, leave the basis unreviewed rather than guessing.

This step does not add the surcharge to **Navlun Önizleme** and does not authorize a customer quote, airline booking, capacity/schedule assumption or outbound message.

## Commercial-Air Surcharge Applicability Review (P2-24)

After surcharge amount/unit and application-basis review, an operator may separately confirm whether the surcharge applies across the exact tariff source or only to one confirmed destination row. Destination-specific scope must resolve to a human-confirmed three-letter destination code in that same source.

This review is evidence only. Do not interpret `source_wide` as airline-wide policy, and do not consume the surcharge in freight/pivot preview yet. Routing restrictions, special-cargo conditions, flat-charge quantity semantics and FX remain unresolved until later bounded steps.

## Commercial-Air Surcharge Operational Conditions (P2-25)

After amount/unit, application-basis and applicability-scope review, confirm cargo and routing conditions separately in **Ayarlar → Havayolu Listeleri**. Use **Exact source cargo scope** only when the source cargo scope is known. For routing, choose exact-source all-routing, direct-only, connecting-only or an explicitly evidenced via airport.

Do not infer cargo class or routing from common airline practice. This review still does not add the surcharge to **Navlun Önizleme** and does not authorize FX, customer pricing, capacity/schedule assumptions, booking or outbound communication.

## Reviewed Per-Kg Surcharge Cost Preview (P2-26)

Use the separate **Reviewed Per-Kg Surcharge Cost Preview** only after the surcharge review chain is complete. Supply actual/volumetric weight plus the shipment cargo and routing context. If a reviewed surcharge is via-specific, provide the connecting via airport so the condition can be matched exactly.

Read the result as a partial reference cost only. Included per-kg surcharge lines show the reviewed weight basis and applied kilograms. Flat charges, cross-currency charges and context-mismatched charges stay in the excluded list with a reason. `Base + reviewed per-kg` is not an all-in cost and must not be copied into a customer quote as an authoritative sell price.

Do not use this preview as capacity, schedule, booking or outbound authority. The existing base **Navlun Önizleme** remains surcharge-free by design.


## Commercial-Air Flat Surcharge Quantity-Basis Review (P2-27)

After a flat surcharge has completed amount/unit, application-basis, destination-scope and cargo/routing review, use **Ayarlar → Havayolu Listeleri** to review its quantity basis separately. Choose only the unit supported by the tariff or operational evidence: shipment, AWB, HAWB or MAWB. Every choice requires an operator note.

Do not assume one AWB or one shipment merely because a flat fee exists. P2-27 does not add flat fees to the current reviewed surcharge cost preview; it only records the quantity semantics needed for a later bounded calculation step. If the evidence does not establish the unit, leave it unreviewed rather than guessing.


## Commercial-Air Reviewed Flat Surcharge Count Preview (P2-28)

In **Reviewed Surcharge Cost Preview**, supply a flat count only when an applicable flat surcharge has a completed quantity-basis review and the current shipment evidence establishes the corresponding count. Enter shipment count for `per_shipment`, AWB count for `per_awb`, HAWB count for `per_hawb`, or MAWB count for `per_mawb`. Leave unrelated count fields blank.

No count field has a default. If a fully reviewed same-currency flat surcharge applies to the selected destination/cargo/routing context and its matching count is missing, the preview must stop rather than silently omit or assume the charge. Context-inapplicable and cross-currency flat charges remain visibly excluded.

Read `Base + reviewed surcharge` as a partial reference subtotal only. It is not all-in and does not confirm tariff validity, capacity, schedule, FX, airline rounding, customer selling price, margin, booking or outbound communication. Count inputs are ephemeral and are not persisted as tariff knowledge.

## Commercial-Air Tariff Validity Review (P2-29)

In **Ayarlar → Havayolu Listeleri**, review the exact tariff source validity range separately from upload metadata. Enter the start and end dates supported by the tariff evidence and add an operator note. If the source was uploaded with validity dates, the reviewed boundaries must match those immutable metadata values; otherwise stop and register corrected source evidence rather than overriding it silently.

In **Reviewed Surcharge Cost Preview**, enter **Tarife referans tarihi** only when you want the preview to confirm that the reviewed tariff covers that specific date. Leaving it blank must not imply today. A supplied date without a review, or a date outside the reviewed range, fails closed.

`Tarife geçerliliği DOĞRULANDI` means only that the exact reviewed tariff date range includes the entered reference date. It does not confirm flight capacity, schedule, booking space, FX, customer sell price, margin or outbound authority.

## Commercial-Air Capacity / Schedule Evidence (P2-30)

In **Ayarlar → Havayolu Listeleri**, record airline availability only when there is explicit evidence for the current inquiry and service date. Capture the inquiry reference, destination, routing/via, service date, capacity result, schedule status, flight reference when actually confirmed, evidence channel/reference and a short operator-authored note.

Do not reuse another shipment's confirmation and do not treat a tariff's validity period as space availability. `Available` means only that the cited evidence reported capacity for that inquiry/date; it is not a booking or reservation. `Schedule confirmed` likewise records the cited schedule evidence but creates no booking authority.

P2-30 does not feed the reviewed surcharge cost preview and does not authorize customer pricing, margin, quote sending, airline booking or outbound communication.

## Commercial-Air FX Rate Evidence (P2-31)

In **Ayarlar → Havayolu Listeleri**, record an FX rate only when the current inquiry has explicit evidence. Enter the pair in the displayed direction: `1 BASE = rate QUOTE`. Capture an explicit ISO-8601 effective timestamp with timezone offset plus the evidence source/reference and a short operator-authored note.

Do not reverse the pair mentally or assume the inverse rate, do not use today's rate unless that exact timestamped rate is the cited evidence, and do not reuse another shipment's FX observation. If the pair or timestamp is uncertain, leave the evidence unrecorded rather than guessing.

P2-31 does **not** convert cross-currency surcharges. Reviewed Surcharge Cost Preview continues to show those items as `currency_mismatch_no_fx` and keeps `fx_applied=false`. Customer selling price, margin, quote/send, booking and outbound authority remain outside this step.

## Commercial-Air Explicit FX Consumption Preview (P2-32)

In **Reviewed Surcharge Cost Preview**, leave FX evidence unselected unless the current inquiry requires a cross-currency surcharge conversion and the operator has verified the exact FX record. Select only the evidence whose stored direction is surcharge currency -> freight currency, then enter the same inquiry reference and the exact timezone-aware effective timestamp from that evidence.

If no FX evidence is selected, cross-currency surcharges remain excluded as `currency_mismatch_no_fx`. Do not expect MINAI to choose the latest/nearest rate or invert a reverse pair. A selected evidence record that does not match source SHA, inquiry, direction or timestamp must stop the preview.

Read converted values as partial reference cost only. The UI also preserves source-currency amounts and identifies the FX evidence used. P2-32 does not create customer selling price, margin, quote/send, booking, capacity/schedule or outbound authority.

## Commercial-Air Operational Readiness Preview (P2-33)

After tariff row, surcharge, validity and shipment-specific capacity/schedule evidence have been reviewed, use **Operational Readiness Preview** on the confirmed tariff row. Enter the same inquiry reference used for the availability confirmation and the intended service date. Routing/via context must match the stored availability evidence exactly. If the cost requires cross-currency conversion, explicitly select the matching P2-32 FX evidence and its exact reference timestamp.

Read `Operational evidence COMPLETE` only as confirmation that the tariff is valid for the service date and matching capacity/schedule evidence is positive. Missing availability appears as `availability_evidence_missing`; negative capacity and unconfirmed schedule remain visible blockers. Conflicting exact-context confirmations stop the preview instead of choosing the latest record.

The displayed cost is still a partial reviewed reference cost. P2-33 does not make the customer quote ready, does not add margin, does not approve/send a quote and does not create booking authority or outbound execution authority.

## Commercial-Air Weight Rounding Review (P2-34)

In **Ayarlar → Havayolu Listeleri**, use **Airline Weight Rounding** only when the exact tariff/airline evidence establishes how chargeable weight is handled before weight-break pricing. Choose **No rounding (explicit)** when the evidence explicitly supports no rounding. Choose **Ceiling / yukarı yuvarla** only with the evidenced increment such as `0.5` or `1`; do not enter a customary increment merely to complete the workflow. Add an operator-authored review note.

After review, **Navlun Önizleme**, **Reviewed Surcharge Cost Preview** and **Operational Readiness Preview** expose the rounding provenance. The raw chargeable weight remains visible. A ceiling review rounds upward before tariff break comparison; an explicit no-rounding review stays distinguishable from missing evidence. If no review exists, the previews continue using raw chargeable weight and display rounding as unreviewed.

P2-34 does not change separately reviewed surcharge weight bases and does not make the partial cost customer-ready or bookable. Margin, customer selling price, quote approval/send and airline booking remain outside this step.

## Commercial-Air Additional / Local Cost Evidence (P2-35)

In **Ayarlar → Havayolu Listeleri**, use **Additional / Local Cost Evidence** only when the current inquiry has explicit evidence for a flat cost outside the airline tariff chain. Record the inquiry reference, provider, category, positive amount/currency, exact flat quantity basis (`shipment`, `AWB`, `HAWB` or `MAWB`), evidence source/reference and an operator-authored note.

Use `customs_service_fee` only for a broker/service-provider fee. Do not enter customs duties, taxes, government charges, `/kg` rates, percentages, minimums or tiered formulas into this form. Those require separate future evidence models instead of approximation.

P2-35 only records evidence. The existing **Reviewed Surcharge Cost Preview** and **Operational Readiness Preview** do not automatically consume these records, and their subtotal remains partial. Do not manually add a stored record and then label the result all-in or customer-ready. Explicit cost-consumption, matching counts and any required FX remain a later gate.

## Commercial-Air Explicit Additional / Local Cost Consumption (P2-36)

In **Reviewed Surcharge Cost Preview**, select an **Additional / Local Cost Evidence** record only when it belongs to the current inquiry and exact tariff source. Enter the same inquiry reference and the explicit count required by its stored quantity basis: shipment, AWB, HAWB or MAWB. Merely seeing a stored local-cost record in the list does not include it in the calculation.

For a local cost in another currency, also select the exact P2-32 FX evidence in the direction `local-cost currency -> freight currency` and enter that evidence's exact timezone-aware reference timestamp. Do not invert a reverse pair and do not use latest/nearest FX. Missing count, inquiry mismatch, source mismatch or missing matching FX must stop the preview.

Read **Extended partial subtotal** as `base freight + reviewed airline surcharges + explicitly selected local costs`. It is not proof that all local costs were discovered. Unsupported `/kg`, percentage, minimum/tiered, customs duty/tax and other unmodelled costs may still exist, so the UI must continue to show **ALL-IN DEĞİL**. The same selected subtotal may be displayed inside Operational Readiness, but operational completeness still does not authorize a customer quote or airline booking.

## Commercial-Air Cost Scope Requirements Review (P2-37)

In **Ayarlar → Havayolu Listeleri**, use **Air Cost Scope Requirements Review** for the current inquiry before attempting any later all-in/completeness decision. Review all nine displayed local-cost areas one by one. Leave a category as **Unresolved** when responsibility or applicability is not evidenced; choose **Required** only when that cost area must be resolved for the quoted service, and **Not applicable** only when the current inquiry/service evidence supports that conclusion. Add a rationale for every category plus an overall review note.

The form intentionally starts every category as Unresolved. A saved review may show `Scope classification COMPLETE` once every category is either required or not applicable, but that wording does **not** mean the cost is complete. Required categories still need separately captured and explicitly selected cost evidence where applicable, and unsupported variable/weight-based/percentage/tiered/duty/tax semantics remain outside P2-37.

P2-37 does not change Reviewed Cost Preview or Operational Readiness totals. Do not treat a scope review as all-in confirmation, do not apply customer margin from it, and do not use it as quote/send, booking or outbound authority. Cost-evidence matching remains a later gate.

## Commercial-Air Required Flat Local-Cost Coverage Preview (P2-38)

After a P2-37 cost-scope review exists, use **Required Flat Local-Cost Coverage** on the confirmed tariff row. Select the exact scope review for the inquiry, then select only the P2-35 local-cost evidence records intended for this calculation. Supply matching shipment/AWB/HAWB/MAWB counts and any explicitly required P2-32 FX evidence exactly as in P2-36.

Read `Required flat-cost coverage COMPLETE` narrowly: every P2-37 category marked `required` is represented by a local-cost record that P2-36 successfully consumed, no scope category remains unresolved, and no selected cost contradicts a `not_applicable` classification. Missing required categories and not-applicable conflicts are shown as blockers. Stored but unselected evidence has no coverage effect.

Do not label the subtotal all-in and do not apply customer margin solely because this gate is complete. P2-38 does not model or prove `/kg`, percentage, minimum/tiered, customs duty/tax or unknown future cost semantics, and it creates no quote/send, booking or outbound authority.

## Commercial-Air Cost Completeness Confirmation (P2-39)

In **Settings → Havayolu Listeleri**, first complete the normal tariff/surcharge review, airline weight-rounding review, Cost Scope Requirements Review and required local-cost evidence selection. Then complete **Unsupported Cost Semantics Review** for the same inquiry/source. All five rows start `Unresolved`; choose `Not applicable` only when explicit operational/source evidence supports that conclusion. If an unsupported semantic actually applies but is not priced, choose `Applicable / unresolved`.

In the reviewed-cost panel select the exact Cost Scope Review and Unsupported Cost Semantics Review, then choose only the additional-cost and FX evidence intended for this calculation and enter required shipment/AWB/HAWB/MAWB counts. **Cost Completeness Kontrol Et** confirms only when flat coverage is complete, unsupported semantics are cleared, weight rounding is reviewed and no cost-relevant surcharge exclusion remains. Destination/cargo/routing non-applicable surcharge lines may remain excluded.

`Cost completeness CONFIRMED` is not a customer quote and is not an all-in label. Do not apply/send a customer price from P2-39 alone. Tariff validity, capacity/schedule, customer pricing policy, quote approval and outbound execution remain separate controlled gates.

## Commercial-Air Customer Pricing Preview (P2-40)

Use `Customer Price Preview Hesapla` only after the same screen can produce `Cost completeness CONFIRMED`. Select the active Customer Master record explicitly. Leave quote override empty to use the normal customer-policy/agency-default resolver, or enter an explicit override when an operator is intentionally overriding the normal policy.

Confirm that the result shows the pricing policy source and formula used together with the confirmed air cost basis and preview selling price. If pricing policy is missing or invalid, treat the result as blocked and configure/approve the appropriate policy rather than inventing a margin. Historical accepted-quote learning must not be used as an automatic fallback.

`PRICE PREVIEW` is not a quote. Do not send it to the customer or treat it as booking authority. P2-40 intentionally leaves quote readiness, quote creation/approval, tariff/service-date validity and airline capacity/schedule to subsequent controlled gates.


## Commercial-Air Quote Readiness Gate (P2-41)

Before declaring an air price ready for quote drafting, select the exact customer, tariff row, cost-scope review, unsupported-cost review, local-cost/FX evidence and service date. Provide shipment pickup/delivery address, commodity, gross weight, package quantity/dimensions, cargo-ready date and explicit ADR / temperature-control / high-value states. The gate recomputes P2-39/P2-40 from package volume and gross weight, and independently checks tariff validity plus matching capacity/schedule evidence for the same inquiry/service date.

If the customer supplied no required-delivery date, leave it absent; do not ask only to satisfy the system. If the customer supplied a deadline, the selected availability evidence must include an expected-delivery date at or before the deadline. `QUOTE READY` means the evidence chain is sufficient to proceed to controlled quote creation. It is not a QuoteCase, approval, sent quote or booking.

## Commercial-Air Durable Quote Preparation and Human Approval (P2-42)

After the Air Quote Readiness Gate returns READY, select the matching open air MINA price-request job and run **QuoteCase + Human Approval Hazırla**. The backend ignores any separate shipment draft and reruns readiness from the persisted MINA job shipment. If readiness has become blocked, no durable quote/approval is written and the MINA job stage is unchanged.

A successful preparation creates the normal shared QuoteCase and a `pending` QuoteApproval, links the case to the MINA job, and moves an eligible price-request job to `quote_ready`. The quote review screen shows **Air Readiness Provenance · Frozen Snapshot**, including tariff/source, service evidence, cost basis and pricing provenance. Repeating the exact same preparation returns the existing case; different evidence for an already-linked job is rejected rather than silently replacing it.

Review/revise/approve the quote with the existing quote controls. Revisions preserve the frozen air evidence lineage and require a fresh approval as usual. P2-42 does not send customer mail or create a booking; those remain separate controlled actions.

## Commercial-Air Accepted Quote → Operation Handoff (P2-43)

After the air quote has been approved, actually sent through the normal quote-send controls and explicitly marked **Müşteri Kabul Etti**, open the MINA job. For an air job the road **Operasyonu Başlat** supplier-message panel is replaced by **Havayolu Operasyon Handoff**. Choose **Havayolu Operasyonuna Devret**.

The backend rechecks the current QuoteCase, current approved snapshot, frozen air provenance, current-revision sent evidence and customer-acceptance timeline before writing anything. A successful handoff moves the job to `operation_opened` and displays the airline, route, service/expected-delivery dates, tariff/source row, cost basis, customer price, approval/revision and sent-evidence count from the frozen handoff.

Treat the resulting card as an internal operation handoff only. **BOOKING HENÜZ YOK** means exactly that: no airline message was sent, no capacity booking was created and any flight reference inherited from the earlier availability evidence remains schedule evidence rather than a booking confirmation. Road vehicle/plaka/sürücü controls are intentionally hidden for air jobs at this stage.

## Commercial-Air Outcome Learning Feedback Loop (P2-44)

After an accepted air quote has been handed to operations, open the MINA job and use **Havayolu Öğrenme Geri Beslemesi** when real evidence becomes available. Record whether the quoted tariff was used unchanged, used with a correction, or not used; the actual airline/routing; actual service/delivery dates when known; actual chargeable weight; actual total air cost/currency; correction categories; and a concrete invoice/booking/e-mail/portal/operator evidence reference. Do not fill unknown fields merely to complete the form.

If later evidence corrects an earlier feedback record, use the displayed update flow. The backend creates a new immutable record that explicitly supersedes the prior current feedback; the old record remains in audit history. Route aggregation counts only the current record for each job. Different-currency actual costs remain valid evidence but are excluded from cost-variance learning without explicit FX normalization.

MINAI proposes route-level observations only after enough comparable jobs exist. Review each proposal with an authored note using **Advisory'yi Onayla** or **Reddet**. Even a human-confirmed air advisory is historical context only. On a future confirmed tariff row, **Air Learning Advisory Göster** may display matching airport-pair + airline + routing observations, but those observations do not select the tariff, change the cost, alter the customer price, choose a route or authorize booking/outbound execution.

## Commercial-Air End-to-End Pilot Hardening (P2-45)

Run the P2-45 gate after P2-39 through P2-44 are green. The rehearsal starts from a text-bearing synthetic commercial-air tariff PDF, stores the exact artifact, performs deterministic structure/table/surcharge extraction and human-review transitions, then creates separate inquiry-bound scope, unsupported-cost, local-cost and capacity/schedule evidence for multiple air jobs. Each job must travel through cost completeness, customer pricing, quote readiness, QuoteCase + human approval, durable customer send evidence, explicit acceptance, operation handoff and realized-outcome feedback.

The gate must fail closed for stale tariff validity, Customer Master mismatch, cross-inquiry local-cost reuse, immutable source/review SHA drift, exact semantic duplicate local costs, exact semantic duplicate applicable surcharges and frozen air-context divergence after approval. A failed scenario must not be repaired by implicit latest/nearest evidence selection and must not create a durable quote or operation handoff when the corresponding authority gate has not passed.

The successful rehearsal uses separate inquiry/job evidence until the air route-learning minimum sample counts are reached and confirms that the resulting `air.*` facts remain advisory and non-runtime-authoritative. This P2-45 gate validates the bounded commercial-air learning/quote-preparation core only. It is not evidence of live airline booking, portal/API integration, airline outbound execution or real-time schedule connectivity.

## Pilot Privacy Forward / Signature Hardening (`p1.28-v4`)

Before generating the next authorized sanitized replay receipt, confirm the runtime reports privacy transform `p1.28-v4`. Forward-only customer or supplier messages may legitimately contain the active shipment request inside a leading **Forwarded/Original Message** block; MINAI now removes the forwarding headers and personal contact data while preserving the freight payload. A normal current-message body followed by a forwarded historical thread continues to drop the historical thread.

If a sender signs off and then adds freight information, the transform preserves the later high-confidence operational addendum while removing the sign-off and intervening personal signature block. Treat any unexpected loss of weight, package/dimension, operational date, ADR/temperature, equipment or labelled pickup/loading/delivery facts as a privacy-boundary regression and stop the replay.

Because v4 changes what content is preserved, any authorized replay receipt or readiness evidence produced under `p1.28-v3` or earlier is stale for this build. Run the authorized sanitized replay again on the approved external dataset, then build fresh readiness evidence before evaluating REAL SHADOW PILOT GO. Do not manually edit an older receipt/evidence file to change its privacy-transform version.

## Road Pilot Overlength Guard

During controlled-pilot extraction review, inspect any explicit package length together with width, height and weight. A package longer than **13.60 m (1360 cm)** is outside the simple standard-trailer pilot: do not approve it as an ordinary Tenteli load. The backend should return project/oversize scope exclusion and project/lowbed equipment guidance.

A package exactly 13.60 m long is not excluded from the pilot solely on the length check; all other readiness, dimension, weight, equipment and commodity gates still apply. If authorized sanitized replay contains an overlength case, its expected truth must classify that case as oversize/project using the same shared dimension rule as runtime.

## Regression Isolation Check

Pilot gate regressions that expect commercial progression must carry their own explicit synthetic commercial fixtures rather than passing only because the canonical runner injected an ambient value. `human_operational_flow` is expected to pass both with `MINAI_AGENCY_PRICING_POLICY_JSON` absent and with an unrelated invalid ambient value, because the regression supplies its own deterministic development-only pricing fixture. Do not interpret that fixture as a runtime agency pricing default.

## Canonical Commercial Fixture Isolation

The controlled-pilot regression gate now includes a commercial-fixture isolation check. The provenance-recovery, atomic-transition, human-flow and quote-approval commercial regressions must carry their own synthetic pricing authority and must not depend on `pilot_regression_suite` injecting a valid `MINAI_AGENCY_PRICING_POLICY_JSON` value.

If a commercial regression passes only inside the canonical runner but fails standalone, treat that as a gate-integrity defect. Do not fix it by adding another global environment default. Make the regression declare the exact synthetic commercial authority it needs, and verify it with ambient agency pricing both absent and intentionally invalid.

## Extraction Safety Truth Gate

At the extraction-confirmation screen, do not approve a proposal while ADR status, temperature-control status or high-value status is still unknown. The API returns a validation error and leaves the proposal unconfirmed; it must not create a MINA job or supplier workflow. Resolve each safety field explicitly from customer evidence or operator review, then confirm again.

Treat `false` as valid only when it is explicitly established. An AI-only negative that remained `None` after safety-truth normalization is not permission to proceed. This runtime rule intentionally matches authorized sanitized replay, where a case with unresolved safety truth remains at `extraction_confirmation_required`.

## Customer Email Identity Binding Hardening

For controlled Outlook intake, the extraction proposal now carries the canonical trusted Customer Master name that was established before AI use. Treat this as immutable email identity authority: correct shipment facts during confirmation, but do not change the bound customer to another Master Data record. If the customer association itself is wrong, reject/reprocess the intake rather than overriding the identity in place.

The manual `process-email` fallback in pilot mode must include the real sender address of the approved customer. MINAI verifies that sender against active Customer Master trust rules before parsing. A missing/untrusted/ambiguous sender is a stop condition. If Customer Master sender trust changes after an RFQ workflow was created, later quote progression must return `customer_identity_verification_required` until current identity evidence is safe again; do not bypass this with agency-default pricing.

## Road Pilot Standard-Height Guard

During extraction review, treat package height above **2.85 m (285 cm)** as outside the simple standard-trailer pilot even when it does not exceed the 3.00 m project-cargo threshold. A 286–300 cm package should produce Mega Trailer guidance, human-review risk and pilot-scope exclusion; above 300 cm the existing Lowbed / Project Cargo behavior remains in force.

A package exactly 285 cm high is not excluded solely by this height rule. Continue evaluating length, width, weight, commodity, ADR, temperature, equipment and all other readiness gates independently.

## Authorized Replay Standard-Trailer Dimension Check

Before accepting fresh authorized replay evidence for a release, verify that replay extraction truth uses the same standard-trailer dimension envelope as runtime pilot scope. A package longer than 13.60 m, wider than 2.50 m, or higher than 2.85 m must produce `is_oversize_or_project=true` in replay scoring even when the operational equipment is Mega rather than project/lowbed.

Boundary cases should remain exact: 13.60 m length, 2.50 m width and 2.85 m height are not classified oversize solely from that dimension. Because replay receipts bind exact release code, generate fresh replay evidence after this change before REAL SHADOW PILOT GO; do not reuse an older receipt that was produced with the prior height derivation.

## GTIP / Commodity Conflict Guard

During controlled-pilot extraction review, inspect any `[GTIP CONSISTENCY WARNING]`. The warning means the customer-provided GTIP / HS interpretation and explicit product description disagree. Do not treat the code as authoritative and do not allow that unresolved case into the simple road pilot; obtain customer/customs verification or reprocess corrected evidence first.

A GTIP-bearing shipment with no conflict remains subject to the ordinary pilot gates and is not excluded solely because a GTIP / HS code is present.

## Explicit Equipment Scope Check

During extraction confirmation, inspect any explicit `equipment_type` independently from ADR, temperature and package dimensions. The simple controlled road pilot accepts the default/unspecified equipment path and recognized Tenteli/Curtainsider requests only. Explicit Reefer/Frigo, Mega, ADR-capable, box/closed-body, lowbed/project or unknown equipment requests must return pilot-scope exclusion even when the remaining shipment facts look ordinary.

Do not clear a special-equipment request to make the case fit the pilot. Preserve the requested equipment for operator review and handle that job outside the simple standard-trailer pilot.

## Top-Loading / Crane-Loading Pilot Check

During controlled-pilot extraction review, inspect shipment notes for `Overhead Crane`, `Tavan Vinci`, `Crane Loading` or `Üstten Yükleme`. These are not ordinary Tenteli loading instructions: they require Open Trailer / Platform evaluation and must stay outside the simple standard-trailer pilot even when package dimensions and safety booleans otherwise look normal.

Do not clear the loading instruction merely to make the job pilot-eligible. Preserve any stronger explicit special-equipment or project/heavy requirement if one already exists.

## Bulk / Liquid Cargo Pilot Check

During controlled-pilot extraction review, inspect commodity, shipment notes and package descriptors for explicit bulk/liquid evidence such as `Dökme Yük`, `Sıvı Yük`, `Bulk Cargo`, `Liquid Cargo`, Tanker, Damper or Silobas. These are not ordinary Tenteli cargo and must remain outside the simple standard-trailer pilot even when dimensions and safety booleans otherwise look normal.

If the exact equipment is not yet authoritative, expect `Bulk / Liquid Equipment Review` plus human review rather than an invented Tanker/Damper/Silobas choice. If an explicit special equipment request already exists, preserve it.

## Lithium Battery Risk Check

During extraction review, treat an explicit lithium/lithium-ion battery description as a yellow operational-review signal even when the currently confirmed ADR flag is false. Verify the actual ADR classification, packaging and special handling requirements from customer/operator evidence before relying on the load as ordinary road cargo.

Do not change the ADR flag or equipment merely from the commodity wording. If independent ADR evidence is established, follow the normal ADR equipment and controlled-pilot scope gates; otherwise preserve the confirmed safety truth and the human-review warning.

## Contractual Transit and Special Handling Risk Check

During controlled road-pilot review, inspect shipment notes for explicit transit guarantees, late-delivery penalties, penalty clauses or equivalent contractual delivery commitments. These cases must show red risk and `management_review`; customer quote generation remains blocked until that review is resolved. Do not clear the contract term or invent a special equipment type to make the case progress.

Also surface akreditif / letter-of-credit / strict-document conditions for documentation review and cross-dock / aktarmalı handling for human operational review. These review signals do not by themselves change ADR truth, equipment or pilot cargo-type scope. Do not apply a generic numeric “impossible transit” threshold until route-specific evidence and policy are separately approved.

## Authorized Replay GTIP / Commodity Conflict Check

When preparing the external sanitized replay set, inspect historical inquiries that contain an explicit customer GTIP/HS code together with a conflicting commodity description. For each genuine contradiction, record `expected.facts.gtip_commodity_conflict` as a known `true` fact and expect `pilot_scope_excluded` with no supplier progression. Ordinary cases do not need an explicit false conflict fact.

During replay, confirm that the production parser emits the structured conflict fact and that downstream replay preserves the operator-confirmed conflict through the confirmation boundary. A parser mismatch, lost conflict fact, lost pilot exclusion or supplier progression is safety-critical and invalidates the replay result. Do not satisfy this check by copying or editing the human-readable `[GTIP CONSISTENCY WARNING]` text into expected ground truth.

This change alters authorized replay behavior while keeping JSONL schema version `1.0` backward-compatible. Generate a new replay receipt against the exact release commit; do not reuse a receipt from a build that predates structured GTIP conflict replay evidence.

## Top-Loading Authorized Replay Check

Before accepting an authorized sanitized replay receipt for a release, include top-loading / crane-loading historical cases when the approved dataset contains them. Operator ground truth should use structured `top_loading_required=true`; do not paste free-form shipment notes into the replay contract merely to reproduce the rule.

Verify that the replay produces `pilot_scope_excluded`, Open Trailer / Platform evaluation where no stronger equipment rule applies, and no supplier progression. A replay build that drops the structured fact can incorrectly turn the same confirmed shipment into ordinary Tenteli cargo, so any replay-code change affecting this fact requires a fresh receipt bound to the exact release commit.

### Contractual Transit / Penalty Replay Check

Before accepting authorized sanitized replay evidence for a release, include any approved historical case that contains a guaranteed transit time, delay penalty, penalty clause or equivalent contractual timing liability with operator-confirmed `contractual_transit_risk=true`. Its expected disposition must be `management_review`, and supplier progression must be false.

A replay that turns such a case into ordinary supplier RFQ progression is not acceptable evidence even if extraction fields otherwise match. Because this changes the replay disposition/evidence contract, generate a fresh replay receipt against the exact release commit after merge; do not reuse an earlier receipt.

## Bulk / Liquid Replay Evidence Check

For sanitized historical cases where bulk/liquid or Tanker/Damper/Silobas need is explicit, record operator-confirmed `bulk_liquid_equipment_review_required=true`. Expected disposition is `pilot_scope_excluded`; supplier progression must be `false`. Verify the authorized replay preserves the exclusion and `Bulk / Liquid Equipment Review` decision. A receipt from a commit before this replay-contract change is not valid evidence for the new release.

### Yellow Human-Review Replay Check

For historical cases with explicit letter-of-credit / strict-document terms, record `strict_document_review_required=true`; for cross-dock / transfer handling, record `cross_dock_review_required=true`. Set `human_review_expected=true` while keeping the expected operational disposition at the actual non-blocking stage (normally `supplier_rfq_approval_required`). A replay that preserves progression but drops the required human review must FAIL safety evidence. Any release containing this replay-contract change requires a fresh authorized sanitized replay receipt for that exact release commit.

### Lithium Battery Human-Review Replay Check

For sanitized historical cases where lithium battery / lithium-ion / lityum batarya / lityum pil evidence is explicit, record operator-confirmed `lithium_battery_review_required=true` and `human_review_expected=true`. Keep `is_adr` independently confirmed; do not infer ADR from lithium text alone.

Verify that authorized replay preserves the human-review requirement without inventing special equipment, management review, or pilot exclusion solely from this fact. Generate a fresh replay receipt against the exact release commit after any change to this replay evidence contract.

### Explicit Source Operational Evidence Check

Before accepting an exact-release replay receipt, include sanitized cases for any available historical inquiry containing explicit top-loading, bulk/liquid special-equipment, lithium-battery, strict-document, cross-dock or contractual-transit/penalty language. The production extraction path must emit the corresponding structured fact even if the model does not preserve the phrase in free-form notes.

Verify ordinary freight text does not invent these flags, and verify lithium source evidence does not itself establish ADR truth. A release where explicit source evidence disappears merely because optional model fields were omitted is not acceptable pilot evidence; generate a fresh authorized sanitized replay receipt after any change to this recovery logic.

### Turkey Shipment Holiday Risk Check

For an approved Road replay/pilot case with a Turkey loading point and explicit ready date, include a verified full-day holiday (for example 30 August or 29 October) or half-day eve when the sanitized dataset contains such evidence. The expected risk is yellow human review while quote generation and simple-pilot eligibility remain otherwise unchanged. Apply the same check to an explicit Turkey delivery date.

Verify foreign-only shipments do not inherit the Turkey holiday warning. For a Turkey shipment date outside the verified holiday-calendar coverage years, expect a human-review warning that the calendar is unverified rather than a fabricated holiday/no-holiday decision. No foreign holiday calendar or pre/post-holiday buffer is authorized by this check. Generate fresh exact-release authorized sanitized replay evidence before pilot GO.
