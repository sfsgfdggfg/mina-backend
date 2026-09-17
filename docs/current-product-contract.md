# Current Pilot Product Contract

This file is the concise current authority index. Decision and rule logs remain append-only; where historical language conflicts, the latest Accepted superseding entry controls.

- **Road-only pilot:** Air workspace is hidden and its settings APIs are not called by the UI unless `MINAI_PILOT_AIR_WORKSPACE_ENABLED=1` explicitly enables it. This does not expand API authorization.
- **Approved jobs:** customer quote stages are skipped and forbidden, but supplier pricing is mandatory. A current usable source-neutral offer must be explicitly selected and durably snapshotted before operation opens; stale evidence requires re-selection.
- **Supplier import:** Settings → Tedarikçiler supports bounded safe `.xlsx`/`.csv` inspect, mapping, preview and state-bound apply. Duplicates/invalid rows are skipped and existing records are not overwritten.
- **Customer documents:** deferred and not needed for the current pilot; there is no customer-documents screen.
- **Mailbox setup:** normal IMAP setup is mailbox email, password and authorization. Host/port/username/certificate pin are advanced fields and may resolve from safe `MINAI_IMAP_DEFAULT_*` deployment defaults/fallbacks. Read-only and secret-storage guarantees remain in force.
- **Password change:** authenticated users may change their own password when external `MINAI_WEB_PASSWORD_OVERRIDES_PATH` is configured. Current password, confirmation, 10–128 characters, external supported-scrypt-only persistence and all-session invalidation apply.
- **Road dates:** firm Road RFQ requires cargo-ready date. Required delivery date is optional unless supplied by the customer; supplied values must be parseable/coherent and respected downstream. DEC-294 and RULE-305 supersede earlier mandatory-delivery-date wording.

Primary current entries for this patch: DEC-291 through DEC-294 and RULE-302 through RULE-305.
