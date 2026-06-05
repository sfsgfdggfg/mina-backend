# MINAI Freight OS

# MVP Architecture v1

## Purpose

Bu doküman MINAI Freight OS MVP v1’in teknik mimarisini tanımlar.

MVP amacı:

* Gelen müşteri mailini almak
* Müşteriyi tanımak
* Shipment bilgilerini çıkarmak
* Eksik bilgi ve riskleri analiz etmek
* Uygun ekipman kararını vermek
* Tedarikçi seçimi yapmak
* Supplier quote toplamak
* Müşteriye quote email taslağı oluşturmak
* İnsan onayı ile teklif gönderimine hazır hale getirmek

---

# 1. MVP Scope

## Included

MVP v1 kapsamında olacaklar:

* Road Freight
* Email → Quote workflow
* Semi-auto çalışma
* Human approval
* Customer Recognition
* Shipment Extraction
* Equipment Decision
* Risk Assessment
* Supplier Selection
* Supplier Quote Parsing
* Quote Draft Generation
* Simulation environment

---

## Not Included

MVP v1 kapsamında olmayacaklar:

* Sea Freight
* Air Freight
* Maersk / MSC portal automation
* WhatsApp automation
* Phone call automation
* Full autonomous sending
* Historical price prediction
* ERP integration

---

# 2. High-Level Architecture

```text
Email Source
    ↓
Email Ingestion Service
    ↓
AI Processing Layer
    ↓
Core Rule Engine
    ↓
Workflow Engine
    ↓
Database
    ↓
Quote Draft Generator
    ↓
Human Review
```

---

# 3. Recommended Tech Stack

## Backend

```text
Python
FastAPI
Pydantic
```

Reason:

* Hızlı geliştirme
* OpenAI entegrasyonu kolay
* API-first yapı
* Tip güvenliği için Pydantic uygun

---

## AI Layer

```text
OpenAI API
Structured Outputs
Prompt Templates
```

Kullanım alanları:

* Email parsing
* Shipment extraction
* Missing info detection
* RFQ drafting
* Quote email drafting

---

## Database

```text
PostgreSQL
```

İlk aşamada yeterlidir.

İleride:

```text
pgvector
```

eklenerek müşteri ve mail geçmişi için semantic search yapılabilir.

---

## Workflow

MVP v1’de workflow önce Python içinde yazılacaktır.

İleride opsiyonel:

```text
n8n
Temporal
LangGraph
```

değerlendirilebilir.

PM kararı:

MVP v1 için workflow sistemi fazla karmaşıklaştırılmayacaktır.

---

## Frontend

İlk aşamada şart değildir.

MVP v1 için yeterli seçenekler:

```text
Terminal output
Simple local dashboard
Streamlit
Basic React UI
```

Öncelik backend ve workflow doğrulamasıdır.

---

## Development Environment

```text
GitHub
GitHub Codespaces
VS Code environment
```

---

# 4. Main Components

## 4.1 Email Ingestion Service

Görev:

* Gelen email’i sisteme almak
* Sender bilgilerini çıkarmak
* Subject ve body bilgisini kaydetmek
* Thread bilgisini saklamak

MVP v1’de iki mod desteklenebilir:

```text
Simulation Mode
Manual Email Input Mode
```

Production’da:

```text
Outlook Graph API
Gmail API
```

eklenebilir.

---

## 4.2 Customer Recognition Service

Görev:

Email’in hangi müşteriye ait olduğunu belirlemek.

Sıralama:

```text
1. Known contact match
2. Known local-part / person match
3. Company domain match
4. Signature recognition
5. Historical context search
6. Manual assignment
```

Public domainler:

```text
gmail.com
hotmail.com
outlook.com
yahoo.com
icloud.com
```

şirket domain’i olarak kullanılmaz.

---

## 4.3 Shipment Extraction Service

Görev:

Düzensiz mail metninden shipment objesi oluşturmak.

Input:

```text
email body
subject
customer context
historical context
```

Output:

```text
Shipment object
confidence score
missing fields
assumptions
```

---

## 4.4 Missing Information Service

Görev:

Shipment için kritik eksik bilgi var mı kontrol etmek.

Road Freight için kritik alanlar:

```text
pickup location
delivery location
piece count
dimensions
commodity
cargo ready date
```

Eksik bilgi varsa:

```text
needs_clarification
```

statüsü oluşur.

---

## 4.5 Equipment Decision Service

Görev:

Yük için doğru ekipmanı belirlemek.

Default:

```text
Tenteli / Curtainsider
```

Override tetikleyicileri:

```text
temperature controlled → Reefer
height > 2.85m → Mega / Lowbed
width > 2.50m → Platform / Lowbed
single piece >= 26t → Lowbed / Heavy Haul
top loading → Open Trailer
high value cargo → Box Trailer
ADR class 1 / 7 → Special ADR equipment
```

---

## 4.6 Risk Assessment Service

Görev:

Shipment risk seviyesini hesaplamak.

Risk seviyeleri:

```text
green
yellow
red
```

Green:

```text
AI quote draft hazırlayabilir.
İnsan onayı yine gerekir.
```

Yellow:

```text
Operasyon personeli incelemesi gerekir.
```

Red:

```text
Yönetici / senior onayı gerekir.
```

---

## 4.7 Supplier Selection Service

Görev:

Shipment için en uygun maksimum 3 tedarikçiyi seçmek.

Input:

```text
route
equipment_type
service_type
customer sensitivity
supplier capabilities
supplier route priority
supplier score
```

Output:

```text
selected_suppliers[]
```

Kural:

```text
RFQ max 3 supplier
```

---

## 4.8 RFQ Generator

Görev:

Tedarikçiye gönderilecek fiyat talep mailini oluşturmak.

RFQ içeriği:

```text
pickup location
delivery location
cargo details
dimensions
weight
equipment requirement
ready date
delivery expectation
special notes
```

---

## 4.9 Supplier Quote Parser

Görev:

Tedarikçiden gelen cevaplardan fiyat bilgisini çıkarmak.

Extracted fields:

```text
quoted_cost
currency
validity
transit time
equipment
notes
```

---

## 4.10 Customer Quote Calculator

Görev:

Müşteriye verilecek satış fiyatını hesaplamak.

MVP formülü:

```text
supplier_cost + margin = final_price
```

Margin tipleri:

```text
percentage
fixed
manual
```

Historical pricing MVP’de otomatik fiyatlama için kullanılmaz.

---

## 4.11 Quote Draft Generator

Görev:

Müşteriye gönderilecek teklif maili taslağını oluşturmak.

Output:

```text
email_subject
email_body
```

Teklif maili insan onayı olmadan gönderilmez.

---

## 4.12 Human Review Layer

Görev:

Operasyon personelinin AI çıktısını kontrol etmesini sağlamak.

Aksiyonlar:

```text
approve
edit
reject
request more info
```

---

# 5. MVP Runtime Modes

## 5.1 Simulation Mode

Amaç:

Gerçek müşteri veya tedarikçi olmadan sistemi test etmek.

Akış:

```text
Fake customer email
↓
AI parsing
↓
Fake supplier response
↓
Quote draft
```

---

## 5.2 Manual Input Mode

Amaç:

Gerçek bir email metnini elle sisteme yapıştırarak test etmek.

Akış:

```text
User pastes email
↓
System processes email
↓
Output shown
```

---

## 5.3 Live Email Mode

MVP sonrası.

Akış:

```text
Outlook/Gmail connector
↓
Inbound email
↓
Workflow engine
```

---

# 6. Suggested Folder Structure

```text
src/

├── main.py
├── config.py

├── ai/
│   ├── email_parser.py
│   ├── quote_generator.py
│   ├── prompts.py

├── core/
│   ├── models.py
│   ├── rules.py
│   ├── pricing.py
│   ├── risk.py
│   ├── equipment.py

├── workflow/
│   ├── pipeline.py
│   ├── customer_recognition.py
│   ├── supplier_selection.py

├── simulation/
│   ├── email_generator.py
│   ├── supplier_simulator.py

├── db/
│   ├── database.py
│   ├── models.py
│   ├── migrations/

└── utils/
    ├── logger.py
```

---

# 7. MVP Development Order

## Step 1 — Simulation Pipeline

```text
Fake email
↓
Shipment extraction
↓
Equipment decision
↓
Risk assessment
↓
Quote draft
```

---

## Step 2 — Structured AI Parser

```text
Email body
↓
Pydantic ShipmentExtraction model
```

---

## Step 3 — Rule Engines

```text
Missing info
Equipment
Risk
```

---

## Step 4 — Supplier Simulation

```text
Selected supplier
↓
Fake supplier quote
```

---

## Step 5 — Quote Draft

```text
Supplier cost
+ margin
↓
Customer quote email
```

---

## Step 6 — Database Integration

Veriler PostgreSQL’e kaydedilir.

---

## Step 7 — Manual Review Screen

Basit bir onay ekranı eklenir.

---

# 8. AI Model Strategy

MVP v1’de model seçimi görev bazlı yapılacaktır.

| Task                | Model Type               |
| ------------------- | ------------------------ |
| Email extraction    | small / cost-efficient   |
| Equipment reasoning | rules first, AI assist   |
| Risk reasoning      | rules first, AI assist   |
| Quote drafting      | medium                   |
| Complex edge cases  | stronger model if needed |

PM kuralı:

```text
Önce deterministic rules.
Sonra AI reasoning.
```

---

# 9. Key Architecture Principle

MINAI yalnızca LLM wrapper olmayacaktır.

Sistem şu yapı üzerine kurulacaktır:

```text
AI Extraction
+
Rule Engine
+
Customer Memory
+
Supplier Intelligence
+
Risk Engine
+
Human Approval
```

---

# 10. Next Step

Bu dokümandan sonra ilk kod aşamasına geçilecektir.

İlk kod hedefi:

```text
Simulation Pipeline v1
```

Amaç:

```text
Tek komutla:
fake email → shipment extraction → risk/equipment decision → quote draft
```

çalıştırmak.
