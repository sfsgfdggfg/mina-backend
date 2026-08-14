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

1. Save the inbound email body in a temporary operator-controlled file, then
   submit it with its identity metadata:

   ```bash
   python -m src.pilot_operator process-email \
     --body-file /approved/input/customer-email.txt \
     --sender-address customer@example.invalid \
     --sender-name 'Customer Contact' \
     --subject 'Freight request' \
     --external-message-id 'mailbox-reference'
   ```

   Record `extraction_proposal.proposal_id`. Review `proposed_shipment`,
   `unknown_fields`, `unknown_safety_fields`, `extraction_status`, and
   `resume_status` in the output. Remove the temporary raw-email file according
   to the approved real-data handling procedure; MINAI does not retain the raw
   body in pilot storage.

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

9. Review and decide the quote approval:

   ```bash
   python -m src.pilot_operator approval list
   python -m src.pilot_operator approval get <approval_id>
   python -m src.pilot_operator case list
   python -m src.pilot_operator case get <case_id>
   python -m src.pilot_operator approval approve <approval_id>
   ```

   The available alternative decisions are:

   ```bash
   python -m src.pilot_operator approval reject <approval_id> --reason 'Reason'
   python -m src.pilot_operator approval invalidate <approval_id>
   ```

   These are lifecycle decisions only. The client has no customer quote-send
   action.

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
| 422 | Input/correction violates the model. Correct the input after reviewing the proposal/RFQ. |
| 503 | Pilot configuration, provenance, or system safety block. Stop until an authorized owner resolves it. |

Safe reads (`status`, `proposal get`, RFQ/approval/case list/get) may be repeated.
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
