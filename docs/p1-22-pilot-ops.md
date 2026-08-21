# P1-22 — Guided Pilot Operations CLI

P1-22 reduces repetitive operator copy/paste around the controlled Outlook smoke
without widening MINAI authority.

## Operator commands

```bash
python -m src.pilot_ops doctor
python -m src.pilot_ops outlook-smoke
python -m src.pilot_ops outlook-smoke verify
python -m src.pilot_ops outlook-smoke prepare
python -m src.pilot_ops outlook-smoke run
```

`doctor` and the default `outlook-smoke` status inspect the current release, the
technical smoke data pack, the private Outlook token cache, silent delegated
authentication, the authenticated pilot runtime, supplier RFQ readiness, and
external smoke evidence. They do not read the mailbox.

The technical smoke pack defaults to:

```text
~/.local/share/minai-outlook-smoke-test
```

Override it only with the deployment-local
`MINAI_OUTLOOK_SMOKE_PACK_DIR`. Before a live prepare/run,
`MINAI_PILOT_DATA_DIR` must resolve to that same verified pack.

Smoke evidence defaults to:

```text
~/.local/share/minai-outlook-smoke-evidence
```

and remains outside the repository. Each prepare creates a private session
directory and the existing P1-21 runner remains authoritative for clean release,
runtime commit matching, two-pass message identity, immutable manifest, receipt,
mailbox-write=false, and automated-send=false checks.

## Human gates

`outlook-smoke verify` requires the operator to review the final data-pack bytes,
enter a verifier identity, and type `REVIEWED`. The CLI then calls the existing
data-pack verification function; it does not invent or bypass provenance.

`outlook-smoke prepare` and `outlook-smoke run` replace the long P1-21
confirmation flag list with four interactive `YES` gates. They still map
one-for-one to the existing live-smoke confirmations.

The CLI never:

- sends customer or supplier mail;
- marks an RFQ as manually sent when no real controlled external send occurred;
- grants Microsoft/OpenAI approval;
- widens Microsoft Graph beyond delegated `Mail.Read`;
- stores or prints access tokens, API keys, operator tokens, or raw mail;
- bypasses the existing P1-21 release/runtime/manifest safety contract.

A supplier smoke reply still requires a real controlled test RFQ to have been
truthfully sent and recorded into the supported response lifecycle before the
mailbox pull.

## Guided controlled supplier RFQ setup

The Outlook smoke status now routes a missing supplier-response lifecycle to:

```bash
python -m src.pilot_ops outlook-smoke setup-rfq
```

This command automates only the mechanical local/API lifecycle needed to prepare
one controlled supplier RFQ. It uses the verified technical smoke pack, sends
synthetic technical inquiry text to the configured OpenAI parser, shows the
extracted shipment for explicit human review, generates the supplier RFQ, and
shows the exact manual-send From/To/Subject/Body.

It never calls an outbound mail adapter. The RFQ is recorded as manually sent
only after the operator types the exact `SENT` confirmation after genuinely
sending the displayed message. A cancelled or non-exact confirmation leaves the
RFQ unrecorded. Re-running after an RFQ is already `awaiting_response` is
idempotent and does not create another inquiry or sent-evidence record.

After PASS, the next real-world action is to reply to that RFQ from the
controlled supplier mailbox so the deterministic RFQ reference arrives in the
configured Outlook pilot inbox for the later four-message live smoke.
