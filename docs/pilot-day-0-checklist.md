# MINAI Pilot Day 0 Checklist

This checklist is the execution gate for the first real controlled shadow-pilot day. It does not replace `docs/pilot-runbook.md`; it turns the existing readiness, replay, approval and operator controls into one ordered launch procedure.

## 0. Pilot Preparation Freeze

- [ ] Feature freeze is active. No new product capability is added before pilot start.
- [ ] Only pilot-blocking bug fixes, safety/regression hardening, deployment/readiness work and documentation changes are allowed.
- [ ] Any code change after the release candidate is frozen creates a new release candidate and invalidates release-bound replay/readiness evidence.
- [ ] Pilot scope remains controlled Road shadow operation; no scope expansion is accepted on Day 0.

## 1. Before Day 0 — Must Already Be Ready

- [ ] Final candidate pilot customers are limited to 2–3 active trusted customer profiles.
- [ ] Final candidate suppliers are limited to 3–5 active contactable suppliers.
- [ ] Customer trusted sender evidence and supplier contact/capability evidence have been reviewed.
- [ ] The external pilot operational data pack is `pilot_verified`, fingerprint-current and frozen for the launch candidate.
- [ ] The external pilot database path, data-pack path and runtime profile are outside the repository.
- [ ] For the first-customer cloud pilot, the Railway service is single-instance in the approved region and its persistent volume is mounted at `/data`.
- [ ] The exact cloud release commit matches the frozen Day 0 release SHA; no unreviewed auto-deploy is pending.
- [ ] The Day 0 runtime uses a dedicated fresh pilot database; smoke/development persistence is preserved separately and is not reused.
- [ ] The seven required approvals are prepared using `docs/pilot-approval-matrix.md`; final attestation still waits for the replay receipt.
- [ ] Outbound mode is `shadow`; autonomous supplier/customer outbound is disabled.
- [ ] Named pilot operators are known and their authenticated access is prepared.
- [ ] A senior Road reviewer is designated for Day 0 review/escalation.
- [ ] Organization approval exists for the controlled shadow pilot.
- [ ] Privacy/legal approval exists for the planned real-data workflow.
- [ ] OpenAI data-control approval exists for the authorized sanitized replay and approved pilot AI use.
- [ ] Deployment/storage approval exists for the selected environment.
- [ ] Retention/deletion procedure is approved and understood by the pilot operators.
- [ ] The agency confirms which authorized mailbox will be connected on Day 0 and that 5–10 historical Road customer inquiries can be selected after connection. No mailbox password needs to be shared with MINAI support, the pilot owner or the implementation team.

## 2. Gate A — Freeze the Exact Release

- [ ] Fetch `origin/main` and record the exact release commit SHA in the external pilot change record.
- [ ] Confirm the release worktree is a dedicated clean pilot-release worktree, not the ordinary development checkout.
- [ ] Confirm no unmerged pilot-blocking fix is waiting.
- [ ] After this point, any release-code change requires restarting Gates A–E on the new exact commit.

**STOP:** dirty worktree, unknown commit, or an unreviewed code change means NO-GO.

## 3. Gate B — Technical and Profile Verification

Run on the exact frozen release:

- [ ] Runtime preflight PASS.
- [ ] Canonical controlled-pilot regression gate PASS.
- [ ] Synthetic full pilot rehearsal PASS.
- [ ] Deployment configuration check PASS: local/private profile uses `pilot_profile_launcher --check-only`; first-customer cloud pilot uses `python -m src.cloud_pilot_launcher --check-only` in the exact deployed environment.
- [ ] Safe launcher/profile resolves the expected external DB and data-pack paths.
- [ ] Cloud pilot reports edge HTTPS enabled, the approved HTTPS base URL, `/data` persistence and the platform port without exposing secrets.
- [ ] Outbound mode still reports `shadow`.
- [ ] Customer dataset PASS.
- [ ] Supplier dataset PASS.
- [ ] Pilot customer cardinality PASS.
- [ ] Pilot supplier cardinality PASS.
- [ ] Dedicated Day 0 SQLite store initializes successfully and contains zero operational state/events before the first real pilot work.

**STOP:** any technical/profile/data check failing is NO-GO. Do not bypass or relabel a failed check.

## 4. Gate C — Agency Mailbox Connection and Authorized Historical Replay

The agency mailbox is connected only now, by an authorized agency operator. Microsoft mailboxes use the approved delegated OAuth flow. IMAP mailboxes use Settings → E-posta; the agency operator enters the mailbox credential directly into MINAI. The mailbox password is never requested from or disclosed to the pilot owner, implementation team or support operator.

- [ ] The authorized agency operator connects the intended mailbox and confirms the displayed mailbox identity/provider.
- [ ] For IMAP, the connection test succeeds before the encrypted credential file is replaced; the password is not returned by any status/API response and the credential file is owner-only under the approved external `/data/auth` storage.
- [ ] For Outlook, delegated authorization remains read-only for shadow/historical work (`Mail.Read` or the explicitly documented discovery scope); no `Mail.Send` is granted for this gate.
- [ ] Daily intake remains explicit/read-only and reports `mailbox_write_performed=false` and `automated_send_performed=false`.

After the connection succeeds, select a small but representative set of 5–10 prior Road customer inquiries from the authorized history. Prefer ordinary complete work, missing-information cases and known edge cases. Include special-equipment/risk cases when available.

- [ ] Raw mail remains transient while the replay source is prepared; the replay JSONL contains only pre-sanitized/pseudonymous content and is stored outside the repository.
- [ ] Real names, real email addresses, phone numbers, unnecessary company identifiers and unrelated sensitive text are removed/replaced.
- [ ] Operational truth needed for evaluation is preserved: lane, dates, dimensions, weight, commodity, equipment, ADR/temperature facts and relevant special conditions.
- [ ] Each replay case contains operator-confirmed historical expected truth.
- [ ] `--confirm-pre-sanitized` is truthful.
- [ ] `--confirm-openai-data-use-approved` is truthful and backed by the real approval; it is not a technical assumption.
- [ ] `--confirm-no-autonomous-outbound` is truthful.
- [ ] Authorized replay runs on the exact frozen release and the final verified operational data pack.
- [ ] Replay result PASS.
- [ ] Safety-critical mismatches = 0.
- [ ] A create-only external replay receipt is generated.
- [ ] Receipt commit SHA matches the frozen release.
- [ ] Receipt operational-data SHA-256 values match the frozen customer/supplier datasets.

**STOP:** any safety-critical mismatch, receipt-binding failure or uncertain sanitization/approval is NO-GO. Investigate before proceeding.

## 5. Gate D — Record Existing Human/Organization Attestations

Use the guided readiness-evidence builder. This step records approvals that already exist; it does not create or grant them.

- [ ] Organization approval attested.
- [ ] Privacy/legal approval attested.
- [ ] OpenAI data-control approval attested.
- [ ] Deployment/storage approval attested.
- [ ] Retention/deletion procedure attested.
- [ ] Named operators attested.
- [ ] Senior Road reviewer attested.
- [ ] Readiness evidence file is created outside the repository and bound to the replay receipt/current release.

**STOP:** never type `CONFIRM` for an approval that has not actually been granted.

## 6. Gate E — Final Readiness Decision

Run the real readiness assessment with the final external profile and readiness-evidence file.

- [ ] Runtime preflight PASS.
- [ ] Canonical regression PASS.
- [ ] Synthetic rehearsal PASS.
- [ ] Release worktree PASS.
- [ ] Real customer dataset PASS.
- [ ] Real supplier dataset PASS.
- [ ] Customer/supplier pilot coverage PASS.
- [ ] Replay operational-data binding PASS.
- [ ] Authorized sanitized replay PASS.
- [ ] All seven human/organization approvals PASS.
- [ ] Autonomous supplier outbound EXPECTED DISABLED.
- [ ] Autonomous customer outbound EXPECTED DISABLED.
- [ ] Final output is exactly `REAL SHADOW PILOT: GO`.

**STOP:** anything other than `REAL SHADOW PILOT: GO` is NO-GO.

## 7. Gate F — Start the Controlled Shadow Runtime

- [ ] Start only through the approved pilot profile/safe launcher path. For the first-customer cloud pilot this is the repository Docker image running `python -m src.cloud_pilot_launcher`.
- [ ] No `--reload`, development server or alternate unvalidated startup path.
- [ ] Public browser access is HTTPS only and the operator reaches `/app/login` through the approved cloud domain.
- [ ] Sibel and the Pilot Owner use separate named browser credentials.
- [ ] Health/status check succeeds.
- [ ] Named operator authentication succeeds.
- [ ] Browser/session access, if used, is through the approved secured pilot shell.
- [ ] Outbound mode is rechecked after startup and remains `shadow`.

## 8. Gate G — One Real-Mail Smoke

Do not process the mailbox in volume immediately after GO. Start with one real inquiry from an approved pilot customer.

- [ ] Pull/process exactly one selected real pilot inquiry.
- [ ] Trusted sender/customer identity resolution is correct.
- [ ] Privacy boundary executes before AI extraction.
- [ ] Extraction remains a proposal until human confirmation.
- [ ] Operator verifies the extracted lane, dates, packages/dimensions, weight, commodity, equipment and safety facts.
- [ ] Human confirmation creates/links the expected MINA job identity.
- [ ] Resume result has the expected pilot scope, equipment and risk decision.
- [ ] Supplier shortlist/RFQ draft is operationally sensible.
- [ ] No supplier/customer message is sent autonomously.
- [ ] Senior Road reviewer agrees that the first-case result is safe to continue.

**STOP:** any safety-critical, identity, privacy, scope or unexpected outbound behavior stops new real-mail processing immediately.

## 9. Gate H — Controlled Observation of the First 3–5 Jobs

For the first 3–5 real jobs, optimize for observation rather than throughput.

For every job compare MINAI with the human operator on:

- [ ] Extraction facts and missing-information decision.
- [ ] Equipment decision.
- [ ] Risk/human-review decision.
- [ ] Pilot-scope decision.
- [ ] Supplier eligibility/ranking/dispatch group.
- [ ] Supplier RFQ wording and required human approval boundary.
- [ ] Supplier response interpretation and commercial safety.
- [ ] Customer quote content, pricing provenance and approval boundary.
- [ ] Timeline/work-queue behavior and operator usability.
- [ ] Any false positive, false negative or confusing recommendation is recorded as pilot evidence.

After 3–5 jobs:

- [ ] Senior Road reviewer performs a short checkpoint review.
- [ ] Continue only if no unresolved safety-critical defect exists.
- [ ] Non-critical usability/product ideas are added to the post-pilot backlog; they do not break feature freeze.

## 10. Stop / Rollback Rule

Immediately stop accepting new real pilot work when any of these occurs:

- safety-critical replay/runtime mismatch;
- trusted-customer identity failure or privacy-boundary failure;
- autonomous/unexpected outbound action;
- incorrect pilot-scope admission for an excluded load;
- durable-state/provenance corruption or inability to reconstruct the active job;
- release/data-pack drift from the evidence-bound hashes;
- senior Road reviewer calls a safety stop.

A stop does not authorize an emergency shortcut. Required sequence is: reproduce → fix narrowly → regression/canonical gate → new exact release → fresh replay receipt → fresh readiness evidence → `REAL SHADOW PILOT: GO` again.

## Current Preparation Snapshot — 2026-09-15

This snapshot is informative only and must be re-run on Day 0.

- Runtime preflight: PASS.
- Canonical controlled-pilot suite: 204/204 PASS on the current release line.
- Synthetic full rehearsal: PASS.
- External pilot profile check: PASS; external DB/data-pack resolved; outbound mode `shadow`.
- Dedicated Day 0 profile/fresh persistence preparation: prepared externally; must be rechecked on the final frozen release.
- Real customer dataset: PASS.
- Real supplier dataset: PASS.
- Pilot customer coverage/cardinality: PASS.
- Pilot supplier coverage/cardinality: PASS.
- Remaining Day 0 evidence: fresh authorized sanitized replay + exact operational-data binding + seven existing human/organization attestations.

## Feature-Freeze Discipline

Until the first controlled pilot checkpoint is completed, new feature ideas go to the strategy/future-work backlog. They are not implemented unless they are proven blockers for safe pilot execution. Pilot-blocking defects may be fixed, but every code fix after release freeze restarts the release-bound replay/readiness gates.
