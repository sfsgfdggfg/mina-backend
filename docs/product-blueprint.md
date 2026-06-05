📦 MINAI Freight OS
Product Blueprint v1
1. Vision

MINAI Freight OS’un amacı:

Uluslararası lojistik ve freight forwarding operasyonlarında, e-posta üzerinden yürüyen tüm operasyonel süreçleri önce AI destekli hale getirmek, ardından kademeli olarak otonomlaştırmak.

Sistem, beyaz yaka operasyon çalışanlarının yaptığı işleri:

anlamlandıran
sınıflandıran
karar destekleyen
ve zamanla yerine geçebilen

AI tabanlı bir operasyon motorudur.

2. Problem Definition

Freight forwarding operasyonlarında süreçler:

Gelen müşteri maillerinin okunması
Shipment bilgilerinin çıkarılması
Eksik bilgilerin tespiti
Tedarikçilere RFQ gönderilmesi
Fiyatların toplanması
Teklif hazırlanması
Müşteriye geri dönüş

Bugün bu süreç:

manuel
dağınık (mail, excel, portal)
kişiye bağımlı
standart dışı

yürütülmektedir.

3. Product Scope (Phase 1)
İlk hedef (MVP):
Road Freight Quote Copilot

Sistem şunları yapar:

Outlook’tan mail okur
Mail içinden shipment bilgilerini çıkarır
Eksik bilgileri tespit eder
Customer history ile karşılaştırır
Supplier seçimi yapar (max 3)
RFQ maili oluşturur
Gelen cevapları analiz eder
Teklif taslağı oluşturur
İnsan onayı ile gönderim yapılır
4. User Types
Freight Forwarder Owner
Operations Staff
Sales Staff
Pricing Team
5. Core Workflow (Phase 1)
Email Received
↓
AI Parsing (Shipment Extraction)
↓
Customer Recognition
↓
Missing Information Check
↓
(If needed) Clarification Email
↓
Supplier Selection (max 3)
↓
RFQ Emails Sent
↓
Supplier Replies Processed
↓
Cost Calculation
↓
Quote Draft Generated
↓
Human Approval
↓
Email Sent to Customer
6. Operational Rules Engine
ROAD-001
Default truck type = Tenteli
if not explicitly specified
ROAD-002
DG cargo is never assumed
must be explicitly stated
RFQ-001
Maximum 3 suppliers per RFQ cycle
OP-001
Critical missing information → clarification required
Non-critical missing information → proceed with assumptions
7. Customer Intelligence

Sistem her müşteri için öğrenir:

geçmiş shipment türleri
sık kullanılan hatlar
araç tercihleri
teslim şekilleri
fiyat hassasiyeti
eksik bilgi toleransı

Bu bilgiler:

RFQ stratejisini
default kararları
iletişim tarzını

etkiler.

8. Supplier Intelligence

Her tedarikçi için:

güçlü olduğu hatlar
fiyat seviyesi
cevap hızı
operasyon kalitesi
DG / özel yük kabiliyeti
gece / acil operasyon performansı

Sistem zamanla öğrenir:

“hangi supplier hangi işte daha başarılı”
9. Pricing Logic (Phase 1)
Road Freight
Supplier price + margin
Sea Freight
Base freight
surcharges
local services (pickup/delivery)
margin
Air Freight
Airline rate
fuel/security surcharge
handling
local services
margin
10. AI Behavior Principles
AI %100 otomatik karar vermez (Phase 1)
İnsan onayı kritik noktalarda zorunludur
AI öneri + taslak üretir
Sistem güvene dayalı değil, doğrulamaya dayalı çalışır
11. System Architecture (High Level)
Core Components:
Email ingestion (Outlook / Graph API)
AI Processing Layer (OpenAI)
Workflow engine (n8n / custom)
Database (PostgreSQL + pgvector)
Frontend dashboard
Supplier communication module
12. Integration Strategy (Phase 1 → Phase 2)
Phase 1
Email-based operations
Manual / semi-automated RFQ
Supplier mail replies
Phase 2
Carrier portals (Maersk, MSC)
API integrations
Browser automation agents
13. MVP Scope Definition
Included:
Road freight only
Email parsing
Supplier RFQ (email)
Quote drafting
Manual approval
Excluded:
Sea freight automation
Air freight automation
Carrier portal automation
Full autonomy
14. Future Vision

Sistem zamanla:

full autonomous freight operator
AI workforce platform
multi-industry expansion (customs, procurement, finance)

haline gelir.

15. Open Questions
Supplier cevap gecikme stratejisi ne olmalı?
Fiyat karşılaştırma kriteri sadece maliyet mi olmalı?
AI hangi durumlarda öneri değil karar verebilir?
Customer memory ne kadar agresif kullanılmalı?
16. Decision Log (Initial)
DEC-001

İlk ürün Road Freight olacak.

DEC-002

RFQ maksimum 3 supplier’a gönderilecek.

DEC-003

Varsayılan araç tipi Tenteli olacaktır.

📌 Not

Bu doküman “canlı doküman”dır.

Her yeni konuşmada:

yeni kural
yeni workflow
yeni karar

eklenecektir.

# Future Opportunities

Bu bölüm MVP kapsamına alınmayan ancak gelecekte değerlendirilmesi planlanan fikirleri içerir.

---

## FUTURE-CANDIDATE-001

### Historical Pricing Intelligence Engine

Amaç:

* Fiyat trendlerini analiz etmek
* Supplier fiyat davranışlarını öğrenmek
* Müşteri fiyat hassasiyetini öğrenmek
* Anormal fiyat değişimlerini tespit etmek
* Operasyon personeline referans fiyat aralığı sunmak

Not:

Road Freight piyasasında fiyatlar günlük değişebildiği için bu modül MVP v1'de otomatik fiyat üretimi amacıyla kullanılmayacaktır.

İlerleyen sürümlerde yeterli veri birikmesi halinde karar destek sistemi olarak değerlendirilecektir.

