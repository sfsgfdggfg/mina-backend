# MINAI Freight OS

MINAI Freight OS, freight forwarding operasyonları için geliştirilen AI destekli bir operasyon asistanıdır.

MVP kapsamı:

* Müşteri emailini okur
* Shipment bilgilerini çıkarır
* Müşteri hafızası ile bilinen müşterileri tanır
* Eksik bilgi kontrolü yapar
* Araç / ekipman kararı verir
* Operasyonel risk seviyesini belirler
* Kararlarının nedenini açıklar
* Sonraki operasyon aksiyonunu önerir
* Teklif, eksik bilgi veya yönetici onayı taslağı üretir
* FastAPI backend ve Streamlit UI ile çalışır

MINAI tam otonom karar verici değildir.

AI’ın görevi:

* talebi analiz etmek
* eksik bilgiyi tespit etmek
* ekipman ve risk kararı önermek
* draft üretmek
* operasyon personeline aksiyon önermek

Son gönderim ve operasyonel karar insan onayına bağlıdır.

---

## Current MVP Flow

```text
Customer Email
↓
AI Structured Parser
↓
Normalization Layer
↓
Customer Memory / Customer Recognition
↓
Missing Info Engine
↓
Equipment Decision Engine
↓
Risk Engine
↓
Workflow Gate
↓
Quote / Clarification / Management Review Draft
↓
Action Recommendation
↓
UI Result Screen
```

---

## Project Structure

```text
data/
├── customer_memory.json
└── backups/

docs/
├── decision-log.md
├── operational-rules.md
├── product-blueprint.md
└── models/
    ├── customer-intelligence-model.md
    ├── database-schema.md
    ├── mvp-architecture.md
    ├── risk-engine.md
    ├── supplier-intelligence-model.md
    └── workflow-engine.md

src/
├── ai/
│   ├── email_parser.py
│   ├── quote_generator.py
│   ├── clarification_generator.py
│   └── approval_generator.py
│
├── core/
│   ├── models.py
│   ├── equipment.py
│   ├── risk.py
│   ├── missing_info.py
│   ├── normalization.py
│   ├── customer_memory.py
│   ├── action_recommendation.py
│   └── pricing.py
│
├── simulation/
│   ├── ai_email_test_cases.py
│   ├── scenario_generator.py
│   ├── supplier_simulator.py
│   └── test_reporter.py
│
├── workflow/
│   └── pipeline.py
│
├── api.py
├── config.py
└── main.py

ui/
└── app.py
```

---

## Documentation

Main documentation files:

```text
docs/decision-log.md
docs/operational-rules.md
docs/product-blueprint.md
docs/models/workflow-engine.md
docs/models/database-schema.md
docs/models/mvp-architecture.md
docs/models/customer-intelligence-model.md
docs/models/supplier-intelligence-model.md
docs/models/risk-engine.md
```

Documentation structure rule:

```text
docs/
→ kararlar, operasyon kuralları ve ürün dokümanları

docs/models/
→ mimari, workflow, veri modeli ve engine dokümanları
```

---

## Setup

### 1. Use the validated Python runtime

MINAI's controlled-pilot runtime is validated only on Python 3.12, specifically
Python 3.12.1 for this dependency baseline. Version managers that honor it can
read `.python-version`; otherwise verify it directly:

```bash
python --version
```

### 2. Install reproducible pilot dependencies

```bash
python -m pip install -r requirements-lock.txt
python -m src.runtime_preflight
```

`requirements.txt` records the human-maintained direct runtime pins.
`requirements-lock.txt` contains their resolved controlled-pilot dependency
closure. `requirements-dev.txt` additionally installs the optional Streamlit
development UI; Streamlit is not pilot-approved.

Run the offline synthetic controlled-pilot rehearsal with:

```bash
python -m src.simulation.pilot_rehearsal
```

See `docs/pilot-runbook.md` for its scope and real-pilot limitations.

Repository-owned data, the provenance registry, and the default pilot database
resolve from the repository location rather than the process working directory.
Continue to start the controlled pilot from the repository root as documented.

### 3. Create `.env`

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

Important:

```text
.env must not be committed to GitHub.
```

---

## Run Backend API (Development Only)

The following wildcard-bind command is for local development only. It is not a
controlled-pilot startup command and must not be used for the shadow pilot:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
```

Backend will run on:

```text
http://127.0.0.1:8000
```

API docs:

```text
http://127.0.0.1:8000/docs
```

Health check:

```text
GET /health
```

---

## Shadow Pilot Startup

Configure the controlled pilot with environment variables supplied by the
deployment environment:

```env
MINAI_PILOT_MODE=true
MINAI_PILOT_BIND_HOST=127.0.0.1
MINAI_PILOT_PORT=8000
MINAI_PILOT_ALLOWED_NETWORKS=127.0.0.1/32
MINAI_PILOT_OPERATORS_JSON={"Pilot Operator":"fake-pilot-token-0000000000000000"}
```

`MINAI_PILOT_BIND_HOST` must be the actual explicit private or loopback IP on
which Uvicorn will listen. Wildcard and public addresses are rejected. The port
is optional and defaults to `8000`; the other values are required for a
non-local pilot network. Replace the obviously fake operator token with a unique
secret of at least 32 characters supplied outside source control.

Start the shadow pilot with exactly this command:

```bash
python -m src.pilot_launcher
```

The launcher always disables reload and forwarded-header/proxy trust, validates
the complete pilot access configuration before serving, and starts only
`src.api:app`. Do not add `--reload`. Streamlit is not pilot-approved and must
not be used for the controlled pilot. The launcher does not enable outbound
email capability.

Operators use the authenticated pilot CLI, not raw API calls or Streamlit:

```bash
export MINAI_PILOT_BASE_URL='http://127.0.0.1:8000'
export MINAI_PILOT_TOKEN='<token-from-approved-secret-store>'
python -m src.pilot_operator status
```

The client accepts only localhost or explicit private/loopback IP destinations,
does not persist or print the token, and exposes no automated send command. See
[`docs/pilot-runbook.md`](docs/pilot-runbook.md) for the controlled workflow,
recovery, emergency stop, backup, retention, and GO/NO-GO procedure.

---

## Run Streamlit UI (Development Only)

Open a second terminal and run:

```bash
streamlit run ui/app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```

If using GitHub Codespaces:

```text
Do not manually open localhost:8501.

Use the Codespaces Ports tab and open the forwarded 8501 URL.
```

The UI allows you to:

* select ready-made test emails
* paste custom customer emails
* process email through MINAI
* view operation summary
* view customer memory match
* view equipment decision explanation
* view risk notes
* view recommended action and checklist
* view generated draft
* run automated test suite
* list customer memory profiles
* add new customer memory profiles
* edit customer memory profiles
* set customer profiles active or passive
* export customer memory data
* import customer memory JSON preview
* validate import files through backend API
* run import dry run
* apply customer memory import with confirmation
* list customer memory backup files
* preview backup restore
* apply backup restore with confirmation
* preview backup cleanup
* apply backup cleanup with confirmation

---

## API Endpoints

Core endpoints:

```text
GET    /health
POST   /process-email
GET    /run-test-suite
```

Customer Memory CRUD endpoints:

```text
GET    /customer-memory
POST   /customer-memory
PUT    /customer-memory
PATCH  /customer-memory/status
```

Customer Memory maintenance endpoints:

```text
GET    /customer-memory/export

POST   /customer-memory/import/validate
POST   /customer-memory/import/dry-run
POST   /customer-memory/import/apply

GET    /customer-memory/backups
GET    /customer-memory/backups/cleanup-preview
POST   /customer-memory/backups/cleanup
POST   /customer-memory/backups/restore
GET    /customer-memory/backups/{file_name}
```

Important API routing rule:

```text
Static routes must be defined before dynamic routes.

Example:
GET /customer-memory/backups/cleanup-preview

must be defined before:
GET /customer-memory/backups/{file_name}
```

---

## Run the Controlled-Pilot Regression Gate

```bash
python -m src.simulation.pilot_regression_suite
```

This is the single canonical local/Codespaces gate for the controlled shadow
pilot. It reports every intentional suite, continues after individual failures,
and exits non-zero if any suite fails. It needs no live AI or network access.
See `docs/regression-suite.md` for membership and retired legacy coverage.

`python -m src.main` remains a legacy development/AI simulation entrypoint. It
requires configured AI behavior and is not a pilot release gate.

Assess readiness for a real controlled shadow pilot with:

```bash
python -m src.pilot_readiness
```

The command is offline and fail-closed. The current demo/unverified datasets and
missing external attestations correctly produce NO-GO (exit `1`). See
`docs/pilot-runbook.md` for the optional external evidence schema and GO rules.

---

## Run Test Suite from UI

In the Streamlit UI:

```text
Run Test Suite
```

Expected result:

```text
10/10 passed, 0 failed
```

---

## Syntax Check

Before accepting major changes:

```bash
python -m py_compile src/api.py
python -m py_compile ui/app.py
```

---

## Example Test Scenarios

The current automated test suite covers:

1. Standard textile FTL
2. Machine missing dimensions
3. Temperature controlled food
4. ADR Class 7
5. Partial shipment request
6. Machine height 2.90m
7. Known customer Oğuz Gıda default equipment
8. Customer recognition from email content
9. Known customer Beta Enerji transformer
10. Known customer Temsa time sensitive automotive

---

## Core Workflow Behavior

### Quote

If information is sufficient and risk is not red:

```text
result_type = quote
```

MINAI generates a customer quote draft.

If risk is yellow, MINAI can still create a quote draft but recommends operational review before sending.

---

### Clarification

If critical information is missing:

```text
result_type = clarification
```

MINAI stops quote generation and creates a missing information email draft.

Examples of critical missing information:

* machine shipment with missing dimensions
* machine shipment with missing weight
* unclear ADR information
* pickup / delivery information too incomplete to start operation
* commodity missing when commodity directly affects equipment decision
* abnormal pallet weight without dimensions

---

### Management Review

If risk level is red:

```text
result_type = management_review
```

MINAI stops quote generation and creates an internal management review draft.

Examples:

* ADR Class 1
* ADR Class 7
* high regulatory risk
* serious operational risk
* management approval required scenarios

---

## Decision Explanation and Action Recommendation

MINAI explains why it made important operational decisions.

For equipment decisions, the system returns:

```text
selected_equipment
reason
confidence
source
explanation
```

Example:

```text
Equipment: Reefer
Reason: Sıcaklık kontrollü yük tespit edildi.
Explanation: Tenteli araç sıcaklık kontrolü sağlayamayacağı için Reefer seçildi.
```

MINAI also recommends the next operational action.

Possible action types:

```text
quote_ready
quote_with_review
clarification
management_review
unknown
```

General mapping:

```text
Green + quote
→ quote_ready

Yellow + quote
→ quote_with_review

Critical missing information
→ clarification

Red risk
→ management_review
```

The UI shows:

```text
Önerilen Aksiyon
Priority
Action Type
Source
Checklist
```

Example:

```text
Action Type: clarification
Priority: high
Title: Müşteriden Eksik Bilgi İste
Checklist:
- Eksik bilgi mail taslağını kontrol et.
- Müşteriden ölçü / ürün / adres / hazır tarih gibi kritik bilgileri iste.
- Bilgi gelmeden fiyat paylaşma.
```

---

## Customer Memory

MINAI can recognize known customers and enrich shipment data using customer-specific memory.

Customer memory profiles are stored in:

```text
data/customer_memory.json
```

Current Customer Memory supports:

* known customer recognition
* customer aliases
* default commodity
* default equipment
* price sensitivity
* time sensitivity
* default pickup / delivery information
* operational notes
* active / passive status
* audit metadata

Example profiles:

```text
Oğuz Gıda
→ default commodity: Meşrubat
→ default equipment: Kapalı Kasa / Box Trailer

Beta Enerji
→ default commodity: Elektrik Transformatörü
→ default equipment: Tenteli / Curtainsider

Temsa
→ default commodity: Otomotiv Parçası
→ time sensitivity: high
```

Customer recognition can happen through:

```text
shipment.customer_name
email_text
```

The UI shows:

```text
Customer Memory Match
Source
Matched By
Operational Notes
Active / Passive status
Audit information
```

---

## Customer Memory Management

The Streamlit UI includes a Customer Memory management module.

Current UI capabilities:

* list existing customer profiles
* add new customer profiles
* edit existing customer profiles
* set profiles active or passive
* prevent duplicate customer names
* prevent duplicate aliases
* prevent unsafe reserved customer names / aliases
* show audit fields

Customer profiles are not physically deleted from the UI.

Instead, MINAI uses active/passive status:

```text
active = true
→ customer can be matched and used for enrichment

active = false
→ customer remains visible in the list but is not used for matching/enrichment
```

Reason:

* prevents accidental loss of customer information
* preserves historical context
* prepares the system for future audit trail support

Current audit fields:

```text
created_at
last_updated_at
last_updated_by
change_note
```

Reserved Customer Memory terms cannot be used as customer names or aliases:

```text
test
demo
deneme
sample
example
dummy
unknown
unknown customer
customer
company
client
müşteri
firma
```

If test customer data is needed, use specific names such as:

```text
Sandbox Customer Alpha
ACME Test Lojistik
Dummy Customer 001
```

---

## Customer Memory Maintenance

MINAI includes customer memory maintenance tools for safer data management.

These tools help operators:

* export customer memory data
* validate imported customer memory files
* preview imports before applying
* apply imports safely
* automatically create backups
* list backup files
* preview restore operations
* apply restore operations safely
* preview backup cleanup
* apply backup cleanup with confirmation

---

### Customer Memory Export

Customer memory can be exported from the Streamlit UI.

The export includes:

```text
export_type
profile_count
profiles
```

API endpoint:

```text
GET /customer-memory/export
```

UI behavior:

```text
Customer Memory Export
↓
Export Customer Memory
↓
Download customer_memory_export.json
↓
JSON Preview
```

Purpose:

* create a portable customer memory backup
* inspect current customer memory data
* prepare data for import / restore testing

---

### Customer Memory Import Preview

Exported customer memory JSON files can be uploaded for preview before import.

This preview does not change:

```text
data/customer_memory.json
```

UI behavior:

```text
Upload customer_memory_export.json
↓
Show profile count
↓
Show customer names
↓
Show raw import preview
```

---

### Customer Memory Import Validation API

Import validation is handled by the backend.

API endpoint:

```text
POST /customer-memory/import/validate
```

Validation checks:

* valid export format
* profiles field exists
* profiles field is a list
* reserved customer names
* reserved aliases
* duplicate customer names inside import file
* duplicate aliases inside import file

Example blocked reserved terms:

```text
test
demo
deneme
sample
example
dummy
unknown
customer
company
client
müşteri
firma
```

---

### Customer Memory Import Dry Run

Before applying an import, MINAI compares the uploaded JSON with the current customer memory file.

API endpoint:

```text
POST /customer-memory/import/dry-run
```

Dry run report shows:

```text
current_profile_count
profile_count
will_add
will_update
will_skip
alias_conflicts
```

Meaning:

```text
will_add
→ profiles that do not exist yet and would be added

will_update
→ profiles that already exist and would be updated

will_skip
→ invalid or incomplete profiles that would not be imported

alias_conflicts
→ aliases that conflict with another existing customer profile
```

---

### Customer Memory Import Apply

Validated customer memory data can be applied from the UI.

API endpoint:

```text
POST /customer-memory/import/apply
```

Safety rules:

* import must pass backend validation
* import must pass dry run conflict checks
* alias conflicts block import
* UI requires checkbox confirmation
* a backup is automatically created before import

Import behavior:

```text
Existing customer profile
→ update existing profile

New customer profile
→ add new profile

Profiles not included in import file
→ remain unchanged
```

Backup location:

```text
data/backups/
```

---

### Customer Memory Backup List

Whenever an import or restore is applied, MINAI creates a timestamped backup.

Backup files are stored in:

```text
data/backups/
```

API endpoint:

```text
GET /customer-memory/backups
```

Backup list includes:

```text
file_name
path
size_bytes
modified_at
```

---

### Customer Memory Restore Preview

Backup files can be previewed before restore.

API endpoint:

```text
GET /customer-memory/backups/{file_name}
```

The UI also runs a restore dry run by using:

```text
POST /customer-memory/import/dry-run
```

Restore preview shows:

```text
Current profile count
Backup profile count
Restore would add
Restore would update
Restore would skip
Alias conflicts
```

No data is changed during preview.

---

### Customer Memory Restore Apply

A selected backup file can be restored from the UI.

API endpoint:

```text
POST /customer-memory/backups/restore
```

Safety rules:

* restore can only use files from `data/backups`
* selected backup is validated before restore
* alias conflicts block restore
* UI requires checkbox confirmation
* current customer memory is backed up again before restore

Restore behavior:

```text
Selected backup file
↓
Validate
↓
Dry run
↓
Checkbox confirmation
↓
Create backup of current live customer_memory.json
↓
Replace customer_memory.json with selected backup content
```

Result includes:

```text
restored_from
pre_restore_backup_path
restored_profile_count
restored_profiles
```

---

### Customer Memory Backup Cleanup Preview

Backup cleanup preview shows which backup files would be kept and which backup files would be cleanup candidates.

API endpoint:

```text
GET /customer-memory/backups/cleanup-preview
```

Default policy:

```text
keep_latest = 10
```

Preview result includes:

```text
total_backup_count
keep_latest
keep_count
cleanup_candidate_count
backups_to_keep
cleanup_candidates
```

No files are deleted during preview.

---

### Customer Memory Backup Cleanup Apply

Backup cleanup apply deletes old backup files after confirmation.

API endpoint:

```text
POST /customer-memory/backups/cleanup
```

Safety rules:

* latest selected number of backups are preserved
* only cleanup candidate files are deleted
* UI requires checkbox confirmation
* deleted files are reported
* failed deletions are reported

Cleanup result includes:

```text
success
keep_latest
deleted_count
failed_count
deleted_files
failed_files
message
```

---

### Current Maintenance Flow

```text
Export
↓
Import Preview
↓
Backend Validation
↓
Dry Run
↓
Apply Import
↓
Automatic Backup
↓
Backup List
↓
Restore Preview
↓
Restore Apply
↓
Cleanup Preview
↓
Cleanup Apply
```

This gives MINAI a safer customer memory maintenance workflow before connecting real customer data sources.

---

## Data Safety Notes

Customer Memory affects operational decisions.

Therefore:

* Customer Memory changes should be tested
* import and restore require validation
* import and restore require dry run
* import and restore create backups
* cleanup requires preview and confirmation
* backup files should be handled carefully
* `.env` must never be committed

Recommended policy:

```text
Customer Memory source file:
data/customer_memory.json

Backup files:
data/backups/
```

---

## Development Rule

After every important change, run:

Run the controlled-pilot regression gate documented above.

Before accepting the change, its summary must report zero failed suites.

For important API/UI changes, also run:

```bash
python -m py_compile src/api.py
python -m py_compile ui/app.py
```

---

## Git Workflow

Before starting work:

```bash
git pull origin main
```

After changes:

```bash
git status
git add .
git commit -m "Short commit message"
git push
```

If push is rejected:

```bash
git pull --rebase origin main
git push
```

---

## Current Status

Sanitized historical replay inputs can be defensively validated (external,
pre-sanitized JSONL only) with:

```bash
python -m src.simulation.sanitized_replay --input /approved/external/path/replay.jsonl
```

The P1.5 CLI intentionally stops after validation until an extraction adapter
and real-data use are separately authorized. See `docs/pilot-runbook.md`.

Completed:

* AI structured parser
* normalization layer
* missing info engine
* equipment decision engine
* equipment decision explanations
* risk engine
* customer memory v1
* customer memory data file
* customer recognition from email content
* customer memory source tracking
* customer sensitivity risk notes
* customer memory UI editor
* customer memory list view
* customer memory active/passive policy
* customer memory edit profile
* customer memory audit notes
* reserved customer memory terms protection
* clarification draft generator
* management review gate
* quote draft generator
* action recommendation engine
* action recommendation test coverage
* automated test report
* FastAPI backend
* Streamlit UI
* UI example selector
* UI test suite runner
* UI operation summary
* UI action recommendation checklist
* customer memory export
* customer memory import preview
* customer memory import validation API
* customer memory import dry run
* customer memory import apply
* customer memory backup list
* customer memory restore preview
* customer memory restore apply
* customer memory backup cleanup preview
* customer memory backup cleanup apply
* documentation structure cleanup
* workflow engine documentation
* database schema documentation
* MVP architecture documentation update

---

## Current Technical Risks

Current technical risks / attention points:

* Streamlit / Codespaces port forwarding can produce stale links.
* Customer Memory backup cleanup deletes real files and should be used carefully.
* JSON storage should eventually move to a real database.
* FastAPI dynamic routes must be placed after static routes.
* Every important change must be checked with the automated test suite.

---

## Next Suggested Task

```text
TASK-059 — Supplier Selection Engine v1
```

Purpose:

* define supplier selection inputs
* create route-based supplier capability model
* compare suppliers by operational, commercial, and relationship factors
* avoid choosing supplier only by cheapest price
* prepare future supplier quote comparison workflow
