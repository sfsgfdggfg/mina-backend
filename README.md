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
└── customer_memory.json

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

docs/
└── ...
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
```

### 2. Create `.env`

Create a `.env` file in the project root:

```env
OPENAI_API_KEY=your_openai_api_key_here
OPENAI_MODEL=gpt-4o-mini
```

Important:

`.env` must not be committed to GitHub.

---

## Run Backend API

Start FastAPI:

```bash
uvicorn src.api:app --reload
```

Backend will run on:

```text
http://127.0.0.1:8000
```

API docs:

```text
/docs
```

Available endpoints:

```text
GET    /health
POST   /process-email
GET    /run-test-suite
GET    /customer-memory
POST   /customer-memory
PUT    /customer-memory
PATCH  /customer-memory/status
```

---

## Run Streamlit UI

Open a second terminal and run:

```bash
streamlit run ui/app.py
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

---

## Run Automated Test Suite from Terminal

```bash
python -m src.main
```

Expected result:

```text
AUTOMATED TEST REPORT
AI TEST 1: PASS
AI TEST 2: PASS
AI TEST 3: PASS
AI TEST 4: PASS
AI TEST 5: PASS
AI TEST 6: PASS
AI TEST 7: PASS
AI TEST 8: PASS
AI TEST 9: PASS
AI TEST 10: PASS

SUMMARY:
10 passed, 0 failed
```

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

## Example Test Scenarios

The current test suite covers:

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

## Customer Memory

MINAI can recognize known customers and enrich shipment data using customer-specific memory.

Customer memory profiles are stored in:

```text
data/customer_memory.json
```

Current customer memory supports:

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

The Streamlit UI includes a basic Customer Memory management module.

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

Reserved customer memory terms cannot be used as customer names or aliases:

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

If test customer data is needed, use specific names such as:

```text
Sandbox Customer Alpha
ACME Test Lojistik
Dummy Customer 001
```

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

## Current System Behavior

### Quote

If information is sufficient and risk is not red:

```text
result_type = quote
```

MINAI generates a customer quote draft.

If risk is yellow, MINAI still creates a quote draft but recommends operational review before sending.

---

### Clarification

If critical information is missing:

```text
result_type = clarification
```

MINAI stops quote generation and creates a missing information email draft.

---

### Management Review

If risk level is red:

```text
result_type = management_review
```

MINAI stops quote generation and creates an internal management review draft.

---

## Development Rule

After every important change, run:

```bash
python -m src.main
```

Before accepting the change, test result should be:

```text
10 passed, 0 failed
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

---

## Next Suggested Task

```text
TASK-049 — Customer Memory Backup / Export v1
```

Purpose:

* export customer memory data
* create backup copy of customer_memory.json
* prepare safer customer memory maintenance workflow
