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
