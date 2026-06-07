# MINAI Freight OS

MINAI Freight OS, freight forwarding operasyonları için geliştirilen AI destekli bir operasyon asistanıdır.

MVP kapsamı:

* Müşteri emailini okur
* Shipment bilgilerini çıkarır
* Eksik bilgi kontrolü yapar
* Araç / ekipman kararı verir
* Operasyonel risk seviyesini belirler
* Teklif, eksik bilgi veya yönetici onayı taslağı üretir
* FastAPI backend ve Streamlit UI ile çalışır

---

## Current MVP Flow

Customer Email
↓
AI Structured Parser
↓
Normalization Layer
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
UI Result Screen

---

## Project Structure

```text
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
GET  /health
POST /process-email
GET  /run-test-suite
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
* view generated draft
* run automated test suite

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

SUMMARY:
6 passed, 0 failed
```

---

## Run Test Suite from UI

In the Streamlit UI:

```text
Run Test Suite
```

Expected result:

```text
6/6 passed, 0 failed
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

---

## Current System Behavior

### Quote

If information is sufficient and risk is not red:

```text
result_type = quote
```

MINAI generates a customer quote draft.

### Clarification

If critical information is missing:

```text
result_type = clarification
```

MINAI generates a missing information email draft.

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
6 passed, 0 failed
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
* risk engine
* clarification draft generator
* management review gate
* quote draft generator
* automated test report
* FastAPI backend
* Streamlit UI
* UI example selector
* UI test suite runner

---

## Next Suggested Task

```text
TASK-029 — Customer Memory v1
```

Purpose:

* known customer recognition
* default customer products
* default pickup/delivery locations
* customer-specific operational rules
