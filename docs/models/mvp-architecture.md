# MINAI Freight OS

# MVP Architecture v2

## 1. Amaç

Bu doküman MINAI Freight OS MVP mimarisini tanımlar.

MINAI Freight OS’in ilk MVP hedefi:

```text
Customer Email
↓
Shipment Analysis
↓
Missing Info / Equipment / Risk Decision
↓
Quote / Clarification / Management Review Draft
↓
Human Approval
```

Sistem tam otonom çalışmak için değil, operasyon personeline karar desteği vermek için tasarlanmıştır.

---

## 2. MVP Kapsamı

MVP kapsamı şu ana akışla sınırlıdır:

```text
Email → Analysis → Draft
```

MVP’nin ana çıktıları:

* quote draft
* clarification email draft
* management review draft
* action recommendation
* customer memory enrichment
* operational risk visibility

---

## 3. MVP Dışı Konular

Aşağıdaki başlıklar MVP kapsamı dışındadır:

* gerçek booking açma
* invoice oluşturma
* gerçek supplier portal entegrasyonu
* gerçek email gönderimi
* ERP entegrasyonu
* CRM entegrasyonu
* otomatik müşteri fiyat gönderimi
* tam otonom operasyon
* historical pricing ile otomatik fiyat oluşturma
* gerçek database migration

Bu konular ileride ayrı fazlarda ele alınacaktır.

---

## 4. Ana Mimari

Mevcut MVP mimarisi:

```text
Customer Email
↓
AI Parser
↓
Normalization Layer
↓
Customer Memory
↓
Missing Info Engine
↓
Equipment Decision Engine
↓
Risk Engine
↓
Workflow Pipeline
↓
Pricing Simulation
↓
Draft Generator
↓
Action Recommendation
↓
FastAPI
↓
Streamlit UI
```

---

## 5. Proje Klasör Yapısı

```text
data/
├── customer_memory.json
└── backups/

docs/
├── decision-log.md
├── operational-rules.md
├── workflow-engine.md
├── database-schema.md
└── mvp-architecture.md

src/
├── ai/
│   ├── email_parser.py
│   ├── quote_generator.py
│   ├── clarification_generator.py
│   └── approval_generator.py
│
├── core/
│   ├── models.py
│   ├── normalization.py
│   ├── missing_info.py
│   ├── equipment.py
│   ├── risk.py
│   ├── pricing.py
│   ├── customer_memory.py
│   └── action_recommendation.py
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

## 6. Backend Architecture

Backend Python tabanlıdır.

Ana backend bileşenleri:

```text
AI Parser
Core Engines
Workflow Pipeline
Simulation Layer
FastAPI API Layer
```

Backend’in merkezi orkestrasyon noktası:

```text
src/workflow/pipeline.py
```

Ana fonksiyon:

```text
process_shipment()
```

---

## 7. AI Parser Layer

AI Parser müşteri mailinden structured shipment bilgisi çıkarır.

Dosya:

```text
src/ai/email_parser.py
```

Görevleri:

* müşteri mailini okumak
* POL / POD çıkarmak
* weight / volume / dimensions çıkarmak
* commodity çıkarmak
* shipment type sinyallerini okumak
* ADR / temperature / equipment sinyallerini okumak
* müşteri adı bilgisini çıkarmak

Parser çıktısı doğrudan operasyon kararına bağlanmaz.

Parser sonrası normalization layer çalışır.

---

## 8. Normalization Layer

Normalization Layer farklı dillerde ve formatlarda gelen değerleri canonical değerlere çevirir.

Dosya:

```text
src/core/normalization.py
```

Örnek dönüşümler:

```text
machine → Makine
Turkey → Türkiye
Germany → Almanya
full truck / komple → FTL
partial / parsiyel → LTL
```

Amaç:

* AI parser çıktısını standartlaştırmak
* workflow kararlarını daha tutarlı hale getirmek
* test edilebilirliği artırmak

---

## 9. Customer Memory Architecture

Customer Memory sistemi CRM değildir.

Amacı:

```text
Known customer → operational defaults / assumptions / notes
```

Current storage:

```text
data/customer_memory.json
```

Customer Memory destekleri:

* known customer recognition
* aliases
* active / passive status
* default commodity
* default equipment
* default pickup / delivery
* price sensitivity
* time sensitivity
* operational notes
* audit metadata

Audit alanları:

```text
created_at
last_updated_at
last_updated_by
change_note
```

---

## 10. Customer Memory Matching

Customer Memory iki kaynaktan eşleşebilir:

```text
shipment.customer_name
email_text
```

Eşleşme sonucu:

```text
matched
profile
source
matched_by
notes_applied
```

Sadece `active = true` olan profiller matching/enrichment için kullanılabilir.

---

## 11. Customer Memory Safety

Reserved customer memory terms engellenir.

Örnek engellenen değerler:

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

Gerekçe:

AI parser belirsiz müşteri adlarında generic değer üretebilir. Bu değerler Customer Memory ile eşleşirse sistem müşteriyi yanlışlıkla tanınan müşteri kabul edebilir.

---

## 12. Missing Info Engine

Dosya:

```text
src/core/missing_info.py
```

Görevi:

* kritik eksik bilgileri tespit etmek
* workflow’un devam edip edemeyeceğine karar vermek
* clarification gerekip gerekmediğini belirlemek

Critical missing information varsa sistem quote üretmez.

Bu durumda:

```text
result_type = clarification
```

---

## 13. Equipment Decision Engine

Dosya:

```text
src/core/equipment.py
```

Görevi:

* yük bilgisine göre uygun ekipmanı belirlemek
* nedenini açıklamak
* güven seviyesini belirtmek
* UI’da karar açıklaması göstermek

Örnek ekipmanlar:

```text
Tenteli / Curtainsider
Mega Trailer
Reefer
Kapalı Kasa / Box Trailer
Platform
Lowbed
Special ADR Equipment
```

---

## 14. Risk Engine

Dosya:

```text
src/core/risk.py
```

Risk Engine teknik risk motoru değil, Operational Risk Engine’dir.

Risk seviyeleri:

```text
green
yellow
red
```

Genel davranış:

```text
green
→ quote_ready

yellow
→ quote_with_review

red
→ management_review
```

---

## 15. Workflow Pipeline

Dosya:

```text
src/workflow/pipeline.py
```

Workflow sırası:

```text
Customer Memory Enrichment
↓
Missing Information Check
↓
Equipment Decision
↓
Risk Assessment
↓
Workflow Gate
↓
Pricing / Draft / Action Recommendation
```

Ana result type değerleri:

```text
quote
clarification
management_review
```

---

## 16. Workflow Gate Logic

Genel karar mantığı:

```text
Red risk
↓
Management Review

Critical missing information
↓
Clarification

Yellow risk
↓
Quote with Review

Green risk
↓
Quote Ready
```

Critical missing information varsa fiyat üretimi durur.

Red risk varsa yönetici incelemesi gerekir.

Yellow risk varsa quote draft üretilebilir ancak review önerilir.

Green risk varsa quote ready olur.

---

## 17. Pricing Simulation

MVP’de gerçek supplier fiyat sistemi yoktur.

Şu an fiyat simülasyonu kullanılır.

Dosyalar:

```text
src/simulation/supplier_simulator.py
src/core/pricing.py
```

Amaç:

* pipeline’ın uçtan uca çalışmasını sağlamak
* quote draft üretimini test etmek
* ileride gerçek supplier fiyat sistemine zemin hazırlamak

Gerçek fiyat kaynağı ileride supplier maili, portal, API veya rate sheet olabilir.

---

## 18. Draft Generators

Draft generator dosyaları:

```text
src/ai/quote_generator.py
src/ai/clarification_generator.py
src/ai/approval_generator.py
```

Üretilen draft türleri:

```text
quote_draft
clarification_draft
management_review_draft
```

AI nihai maili doğrudan göndermez.

Draft insan onayına sunulur.

---

## 19. Action Recommendation Engine

Dosya:

```text
src/core/action_recommendation.py
```

Görevi:

* workflow sonucunu operasyon personeline aksiyon olarak çevirmek
* priority belirlemek
* checklist üretmek
* UI’da bir sonraki adımı göstermek

Action type değerleri:

```text
quote_ready
quote_with_review
clarification
management_review
unknown
```

---

## 20. API Architecture

API framework:

```text
FastAPI
```

Ana dosya:

```text
src/api.py
```

Mevcut endpoint grupları:

```text
Health
Email Processing
Test Suite
Customer Memory CRUD
Customer Memory Export / Import
Customer Memory Backup / Restore
Customer Memory Cleanup
```

Temel endpointler:

```text
GET  /health
POST /process-email
GET  /run-test-suite
```

Customer Memory endpointleri:

```text
GET    /customer-memory
POST   /customer-memory
PUT    /customer-memory
PATCH  /customer-memory/status
```

Maintenance endpointleri:

```text
GET  /customer-memory/export
POST /customer-memory/import/validate
POST /customer-memory/import/dry-run
POST /customer-memory/import/apply
GET  /customer-memory/backups
GET  /customer-memory/backups/cleanup-preview
POST /customer-memory/backups/cleanup
POST /customer-memory/backups/restore
GET  /customer-memory/backups/{file_name}
```

---

## 21. UI Architecture

UI framework:

```text
Streamlit
```

Ana dosya:

```text
ui/app.py
```

UI görevleri:

* email paste / process
* ready test email seçimi
* result summary
* customer memory match gösterimi
* missing info gösterimi
* equipment decision explanation
* risk assessment
* action recommendation checklist
* generated draft gösterimi
* automated test suite runner
* customer memory list
* customer memory add / edit
* active / passive update
* export / import / backup / restore / cleanup işlemleri

---

## 22. Customer Memory Maintenance Architecture

Customer Memory maintenance ana shipment workflow’undan ayrıdır.

Maintenance akışı:

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

Bu işlemler Customer Memory verisini yönetir.

Shipment workflow ise Customer Memory verisini recognition ve enrichment için kullanır.

---

## 23. Backup Architecture

Backup klasörü:

```text
data/backups/
```

Backup dosya formatı:

```text
customer_memory_backup_<timestamp>.json
```

Backup şu işlemlerden önce alınır:

* import apply
* restore apply

Cleanup policy:

```text
keep_latest = 10
```

Son N backup korunur, daha eski backup dosyaları cleanup candidate olur.

---

## 24. Testing Architecture

Ana test komutu:

```bash
python -m src.main
```

Beklenen sonuç:

```text
10 passed, 0 failed
```

Test case dosyası:

```text
src/simulation/ai_email_test_cases.py
```

Test edilen ana senaryolar:

* standard textile FTL
* machine missing dimensions
* temperature controlled food
* ADR Class 7
* partial shipment request
* machine height 2.90m
* known customer Oğuz Gıda
* customer recognition from email content
* Beta Enerji transformer
* Temsa time sensitive automotive

---

## 25. Development / Runtime Architecture

API çalıştırma:

```bash
uvicorn src.api:app --host 0.0.0.0 --port 8000 --reload
```

UI çalıştırma:

```bash
streamlit run ui/app.py --server.address 0.0.0.0 --server.port 8501 --server.headless true
```

Syntax kontrol:

```bash
python -m py_compile src/api.py
python -m py_compile ui/app.py
```

Test:

```bash
python -m src.main
```

---

### Explicit operational-data sources

Normal application execution uses the repository-owned provenance registry,
customer memory, and supplier capability files. Controlled internal execution,
testing, and rehearsal may instead pass one immutable `OperationalDataSources`
object through the confirmed-shipment workflow. This is source injection only:
it does not authorize data for pilot use. The injected registry must identify
the same resolved files that the workflow reads, and pilot classification,
usability, verifier metadata, and SHA-256 verification remain mandatory.
Customer-memory administration, backups, imports, and restores continue to use
the repository-owned paths and do not inherit read-source injection.

## 26. Human Approval Architecture

MINAI tam otonom çalışmaz.

AI’ın görevi:

* analiz etmek
* eksik bilgi tespit etmek
* risk belirlemek
* ekipman önermek
* draft üretmek
* aksiyon önermek

Son gönderim ve operasyonel karar insan onayına bağlıdır.

---

## 27. Current MVP Status

Tamamlanan ana bileşenler:

* AI structured email parser
* normalization layer
* missing info engine
* equipment decision engine
* equipment decision explanation
* operational risk engine
* workflow pipeline
* quote draft generator
* clarification draft generator
* management review draft generator
* action recommendation engine
* automated test suite
* FastAPI backend
* Streamlit UI
* Customer Memory v1
* Customer Memory CRUD
* Customer Memory active/passive
* Customer Memory audit metadata
* Customer Memory reserved terms
* Customer Memory export
* Customer Memory import preview
* Customer Memory import validation API
* Customer Memory import dry run
* Customer Memory import apply
* Customer Memory backup list
* Customer Memory restore preview
* Customer Memory restore apply
* Customer Memory backup cleanup preview
* Customer Memory backup cleanup apply
* README / docs güncellemeleri

---

## 28. Current Technical Risks

Mevcut teknik dikkat noktaları:

* Streamlit / Codespaces port forwarding bazen stale link üretebilir.
* Customer Memory backup cleanup gerçek dosya silme yaptığı için dikkatli kullanılmalıdır.
* JSON storage ileride database’e taşınmalıdır.
* API endpoint sıralamasında dinamik route’lar sabit route’lardan sonra gelmelidir.
* Test suite her değişiklikten sonra çalıştırılmalıdır.

---

## 29. Next Architecture Priorities

Sıradaki mimari öncelikler:

1. Supplier Selection Engine
2. Supplier Route Capability Model
3. Cost Breakdown Engine
4. Margin Rules Engine
5. Quote Comparison Workflow
6. Customer-specific Pricing Behavior
7. Booking Workflow
8. Document Checklist Workflow
9. Real database migration plan
10. Email inbox integration planning
