# MINAI Pilot Approval Matrix

This document prepares the seven human/organization attestations required by `src.pilot_readiness`. It does not grant approval. The guided readiness-evidence builder may record an attestation only after the underlying approval actually exists.

## Evidence Handling

- Keep approver names/roles, approval references and any legal/security evidence in the approved external pilot change record, not in the repository.
- A single person may cover more than one approval only when the organization has actually assigned that authority; software does not infer authority from job title.
- Day 0 `CONFIRM` means "this approval already exists", not "I would like to approve it now".
- Approval evidence must refer to the final controlled Road shadow-pilot scope and the deployment/data handling actually used on Day 0.

## Approval Matrix

| Readiness key | What must already be approved | Suggested accountable role | Minimum Day 0 evidence |
| --- | --- | --- | --- |
| `organization_approval` | Controlled Road shadow pilot, named pilot participants, feature freeze, pilot scope and stop authority | Business owner / authorized pilot sponsor | External approval reference plus approver role/name |
| `privacy_legal_approval` | Planned real customer/supplier data flow, privacy transform, read-only inbound mail, pre-sanitized replay, retention/deletion boundaries | Privacy/legal authority or formally authorized data owner | Approval explicitly covering the pilot data flow in use |
| `openai_data_control_approval` | Approved OpenAI use for privacy-transformed pilot extraction and the pre-sanitized historical replay | Authorized data/security/privacy owner | Explicit approval for the configured pilot AI use; no assumption from technical capability |
| `deployment_storage_approval` | Clean release worktree, external verified data pack, dedicated fresh pilot DB, TLS/web access, host/storage permissions and shadow outbound mode | Technical/deployment owner | Profile `check-only` plus approval of the selected host/storage arrangement |
| `retention_deletion_approval` | Pilot retention period, deletion/recovery procedure, handling of temporary raw inputs and external replay/readiness evidence | Data owner / privacy / operations owner | Approved procedure and responsible operator acknowledgement |
| `named_operators_confirmed` | Exact named pilot operators and authenticated access; no anonymous/shared operator authority | Pilot owner / operations lead | Current operator directory and successful access-preparation check |
| `senior_road_reviewer_confirmed` | One designated senior Road reviewer with first-case review, 3–5 job checkpoint and safety-stop authority | Road operations lead | Reviewer identity/role recorded externally and availability confirmed |

## Before Day 0

- Collect or reconfirm all seven approvals before launch day where practicable.
- Designate the senior Road reviewer and named operators before historical replay starts.
- Verify the deployment/storage approval applies to the dedicated Day 0 profile and fresh persistence store, not an older smoke/test environment.
- Verify privacy/legal and OpenAI data-control approval cover the exact sanitized replay process that will be used.
- Do not create the final readiness-evidence JSON yet; it must bind to the fresh replay receipt and exact release commit.

## Day 0 Attestation Sequence

1. Freeze the exact release and verified operational data pack.
2. Complete the authorized sanitized historical replay and create the exact-commit replay receipt.
3. Reconfirm that each approval above still applies to that release/profile/data flow.
4. Run `src.pilot_readiness_evidence` and enter `CONFIRM` only for approvals that actually exist.
5. Store the generated readiness-evidence file outside the repository.
6. Run final readiness; anything other than `REAL SHADOW PILOT: GO` is a stop.

## Not Sufficient Evidence

The following are not substitutes for an approval: a passing regression suite, a configured environment variable, an old verbal discussion, the existence of a token/cache, previous smoke-test success, or typing `CONFIRM` without the responsible approval having been granted.
