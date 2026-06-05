# MINAI Freight OS

# Workflow Engine v1

## Purpose

Bu doküman MINAI Freight OS’un MVP v1 için temel operasyon akışlarını tanımlar.

MVP kapsamı:

* Email → Quote
* Road Freight odaklı
* Semi-auto çalışma
* İnsan onaylı teklif gönderimi
* Customer Recognition
* Shipment Extraction
* Equipment Decision
* Risk Assessment
* Supplier Selection
* Quote Drafting

---

# 1. Core Workflow

```text
Inbound Email
↓
Customer Recognition
↓
Shipment Extraction
↓
Missing Information Check
↓
Equipment Decision
↓
Risk Assessment
↓
Supplier Selection
↓
RFQ / Supplier Quote Collection
↓
Customer Quote Calculation
↓
Quote Draft Generation
↓
Human Review
↓
Send Quote Email
```

---

# 2. Workflow Statuses

Shipment kayıtları aşağıdaki statülerde ilerler:

```text
new
parsed
needs_clarification
ready_for_supplier_selection
rfq_sent
supplier_quotes_received
quote_draft_created
pending_approval
approved
sent
rejected
cancelled
```

---

# 3. Customer Recognition Flow

Amaç:

Gelen mailin hangi müşteriye ait olduğunu tespit etmek.

## Step 1 — Known Contact Match

```text
IF sender_email exists in customer_contacts
THEN customer = matched customer
```

## Step 2 — Known Person / Local Part Match

```text
IF sender email local part or sender name is known
THEN customer = related customer
```

Örnek:

```text
selman@temsa.com
↓
Selman bilinen kontak
↓
Customer = TEMSA
```

## Step 3 — Company Domain Match

```text
IF email_domain is not public domain
AND domain exists in customer_domains
THEN customer = matched customer
```

Public domain örnekleri:

```text
gmail.com
hotmail.com
outlook.com
yahoo.com
icloud.com
```

Bu domainler müşteri şirket domain’i olarak kullanılmaz.

## Step 4 — Email Signature Recognition

```text
IF signature contains known company name
THEN suggest customer match
```

## Step 5 — Historical Context Search

```text
Search previous email threads
↓
Find same sender / same company / same route pattern
↓
Suggest possible customer
```

## Step 6 — Manual Assignment

```text
IF confidence is low
THEN ask user to assign customer manually
```

---

# 4. Shipment Extraction Flow

Amaç:

Düzensiz müşteri mailinden yapılandırılmış shipment bilgisi çıkarmak.

## Extracted Fields

```text
transport_mode
direction
service_type
pickup_country
pickup_city
pickup_area
pickup_postcode
delivery_country
delivery_city
delivery_area
delivery_postcode
commodity
piece_count
gross_weight
dimensions
cargo_ready_date
required_delivery_date
equipment_type
special_requirements
```

## AI Output

AI her extraction sonucunda güven skoru üretir.

```text
ai_confidence_score
```

---

# 5. Missing Information Flow

Amaç:

Fiyat çalışmak için kritik eksik bilgi olup olmadığını belirlemek.

## Road Freight Pricing Required Fields

```text
pickup location
delivery location
piece count
dimensions
commodity
cargo ready date
```

## Optional Fields

```text
gross weight
incoterm
required delivery date
```

## Behavior

```text
IF critical field missing
THEN status = needs_clarification

IF non-critical field missing
THEN continue with assumption or customer memory
```

---

# 6. Clarification Flow

Amaç:

Eksik kritik bilgi varsa müşteriye net ve kısa bilgi talep maili hazırlamak.

## Example Behavior

```text
Missing:
- dimensions
- commodity

AI generates clarification email
Human reviews
Email sent
```

Clarification maili insan onayı olmadan gönderilmez.

---

# 7. Equipment Decision Flow

Amaç:

Yük için uygun ekipmanı belirlemek.

## Default Rule

```text
IF no special requirement
THEN equipment_type = Curtainsider / Tenteli
```

## Override Triggers

### Reefer

```text
IF temperature controlled
OR frozen
OR chilled
OR +4°C
OR -18°C
THEN equipment_type = Reefer
```

### Mega / Lowbed

```text
IF height > 2.85m AND height <= 3.00m
THEN equipment_type = Mega

IF height > 3.00m
THEN equipment_type = Lowbed / Project Cargo
```

### Lowbed / Heavy Haul

```text
IF single piece weight >= 26 tons
THEN equipment_type = Lowbed / Heavy Haul
```

### Open Trailer

```text
IF crane loading
OR overhead crane
OR top loading
THEN equipment_type = Open Trailer
```

### Box Trailer

```text
IF high value cargo
OR theft risk cargo
THEN equipment_type = Box Trailer
```

### Platform / Lowbed

```text
IF width > 2.50m
THEN equipment_type = Platform / Lowbed
```

---

# 8. Risk Assessment Flow

Amaç:

Shipment’ın operasyonel risk seviyesini belirlemek.

Risk seviyeleri:

```text
green
yellow
red
```

## Green

Standart operasyon.

```text
AI can prepare quote draft
Human approval still required before sending
```

## Yellow

Operasyonel dikkat gerektirir.

```text
Human review required
```

Örnekler:

```text
new customer
tight delivery deadline
cross-docking
holiday period
machine cargo with incomplete details
```

## Red

Yönetim veya senior operasyon onayı gerekir.

Örnekler:

```text
ADR Class 1
ADR Class 7
Lithium batteries
war zone / embargo region
penalty clause
guaranteed transit commitment
heavy lift / oversize
letter of credit with strict document terms
```

---

# 9. Supplier Selection Flow

Amaç:

Shipment için en uygun maksimum 3 tedarikçiyi seçmek.

## Input

```text
origin country / region
destination country / region
service_type
equipment_type
customer sensitivity
risk level
supplier capability
supplier score
```

## Supplier Filter

```text
Filter by route
Filter by equipment capability
Filter by service type
Filter by active status
```

## Supplier Scoring

Tedarikçi seçimi sadece fiyata göre yapılmaz.

Skor bileşenleri:

```text
operational_score
commercial_score
relationship_score
response_speed_score
on_time_score
damage_score
flexibility_score
```

## Customer Sensitivity Adjustment

```text
IF customer is time_sensitive
THEN operational_score weight increases

IF customer is price_sensitive
THEN commercial_score weight increases
```

## Output

```text
Max 3 suppliers selected
```

---

# 10. RFQ Flow

Amaç:

Seçilen tedarikçilere fiyat talep maili hazırlamak.

## RFQ Email Includes

```text
pickup location
delivery location
cargo details
piece count
dimensions
weight
equipment requirement
ready date
delivery expectation
special notes
```

## Behavior

```text
AI prepares RFQ email
Human can review
System sends RFQ
```

MVP v1’de RFQ gönderimi insan onaylı olabilir.

---

# 11. Supplier Quote Collection Flow

Amaç:

Tedarikçiden gelen fiyatları shipment ile ilişkilendirmek.

## Process

```text
Supplier replies by email
↓
AI detects quoted price
↓
AI detects currency
↓
AI detects validity
↓
AI detects equipment / transit note
↓
Record saved to supplier_quotes
```

---

# 12. Customer Quote Calculation Flow

Amaç:

Müşteriye verilecek satış fiyatını oluşturmak.

## Input

```text
selected supplier quote
customer margin rules
manual margin override
currency
risk notes
```

## MVP Pricing Rule

```text
supplier_cost
+ margin
= final_price
```

Margin yapısı şirket veya müşteri bazlı değişebilir.

MVP v1’de:

```text
margin_type:
- percentage
- fixed
- manual
```

desteklenir.

Historical pricing MVP’de otomatik fiyat üretimi için kullanılmaz.

---

# 13. Quote Draft Generation Flow

Amaç:

Müşteriye gönderilecek teklif maili taslağını hazırlamak.

## Quote Draft Includes

```text
route
cargo summary
equipment type
price
currency
validity
transit time if available
service conditions
risk / assumption notes if needed
```

## Output

```text
quote_drafts.email_subject
quote_drafts.email_body
```

---

# 14. Human Approval Flow

Amaç:

AI tarafından hazırlanan teklifin insan tarafından kontrol edilmesini sağlamak.

## Actions

```text
approve
edit
reject
request more info
```

## Behavior

```text
IF approved
THEN quote_status = approved

IF sent
THEN quote_status = sent
```

Müşteriye teklif maili insan onayı olmadan gönderilmez.

---

# 15. Audit Flow

Amaç:

Sistemin önemli kararlarını kayıt altına almak.

Loglanan olaylar:

```text
customer matched
shipment parsed
risk detected
supplier selected
quote created
quote approved
quote sent
```

Her olay `audit_logs` tablosuna yazılır.

---

# 16. MVP Workflow Summary

```text
1. Email arrives
2. Customer is identified
3. Shipment is extracted
4. Missing info is checked
5. Equipment decision is made
6. Risk level is calculated
7. Suppliers are selected
8. Supplier quotes are collected
9. Customer quote is calculated
10. Quote draft is generated
11. Human approves
12. Quote email is sent
```

---

# 17. Not Included in MVP v1

```text
Full automation
Carrier portal automation
Sea freight pricing
Air freight pricing
Historical price prediction
Automatic sending without approval
WhatsApp automation
Phone call automation
```

---

# 18. Next Step

Bu workflow onaylandıktan sonra sıradaki doküman:

```text
docs/models/mvp-architecture.md
```

olacaktır.

MVP Architecture dokümanında:

```text
FastAPI
OpenAI
PostgreSQL
Email connector
Workflow pipeline
Simulation environment
```

tasarlanacaktır.

