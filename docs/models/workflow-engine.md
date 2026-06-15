# MINAI Freight OS

# Workflow Engine v1

## 1. Amaç

Workflow Engine, MINAI Freight OS içinde müşteri talebinin hangi operasyonel yola gideceğini belirleyen karar katmanıdır.

Bu motorun görevi fiyat hesaplamak değildir.

Ana görevi:

* AI parser çıktısını almak
* normalize edilmiş shipment bilgisini kullanmak
* müşteri hafızasını dikkate almak
* eksik bilgi kontrolü yapmak
* ekipman kararını almak
* operasyonel risk seviyesini değerlendirmek
* quote / clarification / management review kararını vermek
* kullanıcıya önerilen aksiyonu sunmaktır

---

## 2. Genel Akış

```text
Customer Email
↓
AI Email Parser
↓
Normalization Layer
↓
Customer Memory Recognition / Enrichment
↓
Missing Information Engine
↓
Equipment Decision Engine
↓
Operational Risk Engine
↓
Workflow Gate
↓
Action Recommendation Engine
↓
Draft Generator
↓
Human Review / Approval
```

---

## 3. Workflow Engine’in Konumu

Workflow Engine şu dosyada çalışır:

```text
src/workflow/pipeline.py
```

Ana fonksiyon:

```text
process_shipment()
```

Bu fonksiyon sistemin operasyonel orkestrasyon noktasıdır.

---

## 4. Input

Workflow Engine’in ana inputları:

```text
shipment
email_text
```

`shipment`, AI parser ve normalization layer sonrası oluşan yapılandırılmış taşıma bilgisidir.

`email_text`, müşteri mailinin ham metnidir. Customer Memory recognition için kullanılabilir.

---

## 5. Output

Workflow Engine tek bir sonuç objesi üretir.

Ana output alanları:

```text
result_type
shipment
customer_memory
missing_info
equipment_decision
risk_assessment
supplier_quote
customer_quote
quote_draft
clarification_draft
management_review_draft
action_recommendation
```

---

## 6. Result Type Değerleri

Workflow Engine şu ana result type değerlerini üretebilir:

```text
quote
clarification
management_review
```

---

## 7. Customer Memory Aşaması

Workflow önce müşteri hafızasını kontrol eder.

Customer Memory şu iki kaynaktan eşleşebilir:

```text
shipment.customer_name
email_text
```

Eşleşme bulunursa sistem aşağıdaki alanlarda enrichment yapabilir:

* customer_name
* default commodity
* default equipment
* default pickup
* default delivery
* operational notes
* price sensitivity
* time sensitivity

Ancak müşteri mailde açık bilgi verdiyse Customer Memory bu bilgiyi ezmez.

Öncelik sırası:

```text
1. Müşterinin güncel mailde verdiği açık bilgi
2. Customer Memory varsayımı
3. AI çıkarımı
4. Clarification request
```

---

## 8. Active / Passive Customer Memory Kuralı

Customer Memory profili sadece şu durumda matching ve enrichment için kullanılabilir:

```text
active = true
```

`active = false` olan profiller:

* UI’da görünür
* geçmiş bilgi olarak saklanır
* matching için kullanılmaz
* enrichment için kullanılmaz

---

## 9. Missing Information Gate

Workflow Engine fiyat üretmeden önce eksik bilgi kontrolü yapar.

Eksik bilgi kontrolü şu modülde yapılır:

```text
src/core/missing_info.py
```

Critical missing information varsa sistem quote üretmez.

Bu durumda:

```text
result_type = clarification
```

ve clarification email draft hazırlanır.

---

## 10. Critical Missing Information Örnekleri

Aşağıdaki durumlar fiyat üretimini durdurabilir:

* Makine yükünde ölçü eksikliği
* Makine yükünde ağırlık eksikliği
* ADR bilgisinin belirsiz olması
* Pickup / delivery bilgisinin operasyonu başlatmaya yetmeyecek kadar eksik olması
* Commodity bilgisinin ekipman kararını doğrudan etkilediği durumlarda eksik olması
* Anormal palet ağırlığı ve ölçü bilgisinin olmaması

---

## 11. Equipment Decision Gate

Eksik bilgi kontrolünden sonra sistem ekipman kararı verir.

Ekipman karar modülü:

```text
src/core/equipment.py
```

Ekipman kararı aşağıdaki bilgileri içermelidir:

```text
selected_equipment
reason
confidence
source
explanation
```

Örnek:

```text
Temperature controlled food
↓
selected_equipment = Reefer
reason = Sıcaklık kontrollü yük tespit edildi.
```

---

## 12. Risk Assessment Gate

Risk değerlendirmesi şu modülde yapılır:

```text
src/core/risk.py
```

Risk seviyeleri:

```text
green
yellow
red
```

Risk motoru teknik risk motoru değildir.

Bu motor Operational Risk Engine olarak çalışır.

Yani amaç yalnızca yükün teknik uygunluğunu değil, operasyonel dikkat seviyesini belirlemektir.

---

## 13. Risk Seviyelerine Göre Davranış

### Green

```text
risk_level = green
↓
quote hazırlanabilir
↓
action_type = quote_ready
```

### Yellow

```text
risk_level = yellow
↓
quote hazırlanabilir
↓
ancak insan kontrolü önerilir
↓
action_type = quote_with_review
```

### Red

```text
risk_level = red
↓
quote süreci durdurulur
↓
management review draft hazırlanır
↓
action_type = management_review
```

---

---

## 14. Supplier Selection Step

Supplier Selection adımı, Risk Assessment sonrasında ve Supplier Quote üretiminden önce çalışır.

Bu adımın amacı, fiyat simülasyonuna veya supplier teklif toplama sürecine geçmeden önce operasyonel olarak en uygun supplier adaylarını belirlemektir.

Güncel workflow akışı:

```text
1. Email parsing
2. Customer Memory enrichment
3. Missing information check
4. Equipment decision
5. Risk assessment
6. Supplier selection
7. Supplier quote simulation
8. Customer quote calculation
9. Quote draft generation
10. Action recommendation
```

Supplier Selection Engine şu bilgileri kullanır:

```text
- Shipment data
- Equipment decision
- Risk assessment
- Service type
- Delivery country / route
- Equipment requirement
```

Supplier seçimi yalnızca en düşük fiyat kriterine göre yapılmaz.

Sistem aşağıdaki faktörleri birlikte değerlendirir:

```text
- Route uygunluğu
- Ekipman uygunluğu
- Servis tipi uygunluğu
- Risk seviyesi
- Supplier güvenilirliği
- Fiyat skoru
- Hız / transit uygunluğu
```

Supplier Selection çıktısı şu yapıdadır:

```json
{
  "selected_suppliers": [
    {
      "supplier_name": "Anatolia Road",
      "priority": 1,
      "total_score": 0.892,
      "route_score": 1.0,
      "equipment_score": 1.0,
      "risk_score": 0.9,
      "price_score": 0.76,
      "speed_score": 0.84,
      "reason": "güzergah uygun; ekipman / servis tipi uygun; risk profiline uygun ve güven skoru yüksek"
    }
  ],
  "rejected_suppliers": [],
  "selection_strategy": "route + equipment + risk + price + speed weighted scoring",
  "source": "supplier_selection_engine"
}
```

Supplier Selection v1 demo supplier profilleriyle çalışır.

Gerçek supplier database, route capability matrix, supplier performans geçmişi ve müşteri-supplier ilişki skorları sonraki geliştirme görevlerinde eklenecektir.

Operasyonel prensip:

```text
- ADR yüklerde ADR uzmanı supplier önceliklendirilir.
- Reefer yüklerde soğuk zincir kabiliyeti olmayan supplier elenir.
- Lowbed / ağır yük taleplerinde proje yükü kabiliyeti olmayan supplier elenir.
- Parsiyel taleplerde LTL / parsiyel network sağlayabilen supplier önceliklendirilir.
```

Supplier Selection Engine en fazla 3 uygun supplier adayı önerir.


## 15. Critical Missing Information Önceliği

Critical missing information varsa risk seviyesinden bağımsız olarak fiyat üretilmez.

Örnek:

```text
Machine shipment
Dimensions missing
↓
result_type = clarification
```

Bu durumda sistem quote draft üretmez.

---

## 16. Management Review Gate

Red risk durumunda sistem yönetici incelemesi ister.

Örnek red riskler:

* ADR Class 1
* ADR Class 7
* savaş / ambargo / siyasi risk bölgeleri
* yüksek seviyeli regülasyon veya güvenlik riski
* operasyonel olarak yönetim onayı gerektiren durumlar

Bu durumda:

```text
result_type = management_review
```

ve internal management review draft hazırlanır.

---

## 17. Quote Generation Gate

Aşağıdaki şartlarda quote draft üretilebilir:

```text
critical missing information yok
red risk yok
```

Yellow risk varsa quote üretilebilir ama kullanıcıya review önerilir.

Green risk varsa quote ready olarak ilerler.

---

## 18. Action Recommendation Engine

Workflow sonucunda sistem kullanıcıya bir sonraki operasyonel aksiyonu önerir.

Modül:

```text
src/core/action_recommendation.py
```

Action type değerleri:

```text
quote_ready
quote_with_review
clarification
management_review
unknown
```

---

## 19. Action Recommendation Mapping

Genel mapping:

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

---

## 20. Draft Generator Davranışı

Workflow sonucu hangi draft’ın üretileceğini belirler.

```text
result_type = quote
↓
quote_draft

result_type = clarification
↓
clarification_draft

result_type = management_review
↓
management_review_draft
```

Aynı anda yalnızca ilgili ana draft kullanılmalıdır.

---

## 21. Human Approval Policy

MINAI nihai müşteri teklifini koşulsuz olarak göndermez.

AI’ın görevi:

* talebi analiz etmek
* eksik bilgiyi tespit etmek
* ekipman önerisi yapmak
* risk seviyesini belirlemek
* draft üretmek
* aksiyon önermek

Son karar ve gönderim insan onayına bağlıdır.

---

## 22. Workflow Öncelik Sırası

Workflow Engine karar önceliği:

```text
1. Red risk var mı?
2. Critical missing information var mı?
3. Yellow risk var mı?
4. Green quote ready mi?
```

Ancak pratik uygulamada critical missing information kontrolü, quote üretimini durdurduğu için her zaman ayrıca dikkate alınır.

Önerilen mantık:

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

---

## 23. Customer Memory Maintenance Workflow

Customer Memory bakım işlemleri ana shipment workflow’undan ayrıdır.

Maintenance workflow şunları içerir:

* export
* import preview
* backend validation
* dry run
* import apply
* automatic backup
* backup list
* restore preview
* restore apply
* cleanup preview
* cleanup apply

Bu işlemler müşteri talebi işleme pipeline’ının parçası değildir.

Ancak Customer Memory verisi shipment workflow’u içinde recognition ve enrichment için kullanılır.

---

## 24. Import Workflow

Customer Memory import süreci:

```text
Upload JSON
↓
Import Preview
↓
Backend Validation
↓
Dry Run
↓
Checkbox Confirmation
↓
Apply Import
↓
Automatic Backup
↓
Updated customer_memory.json
```

Import apply davranışı:

```text
Existing profile
→ update

New profile
→ add

Profiles not included in import
→ remain unchanged
```

---

## 25. Restore Workflow

Customer Memory restore süreci:

```text
Select Backup
↓
Preview Backup
↓
Restore Dry Run
↓
Validation
↓
Alias Conflict Check
↓
Checkbox Confirmation
↓
Backup Current Live File
↓
Restore Selected Backup
```

Restore işlemi yalnızca `data/backups/` içindeki sistem backup dosyalarından yapılır.

---

## 26. Backup Cleanup Workflow

Backup cleanup süreci:

```text
Select keep_latest value
↓
Cleanup Preview
↓
Show Backups to Keep
↓
Show Cleanup Candidates
↓
Checkbox Confirmation
↓
Apply Cleanup
↓
Deleted Files Report
```

Varsayılan politika:

```text
keep_latest = 10
```

Son N backup korunur. Daha eski backup dosyaları cleanup candidate olarak değerlendirilir.

---

## 27. Error Handling İlkeleri

Workflow Engine ve API tarafında hatalar kullanıcıya anlaşılır şekilde dönmelidir.

Genel kurallar:

* Yanlış müşteri hafızası girdisi → 400
* Backup dosyası bulunamadı → 404
* Sistemsel beklenmeyen hata → 500
* Validation başarısızsa işlem uygulanmaz
* Alias conflict varsa import / restore engellenir

---

## 28. Test Politikası

Her önemli değişiklikten sonra şu komut çalıştırılır:

```bash
python -m src.main
```

Beklenen sonuç:

```text
10 passed, 0 failed
```

Ayrıca kritik dosyalar için syntax kontrolü yapılabilir:

```bash
python -m py_compile src/api.py
python -m py_compile ui/app.py
```

---

## 29. Current Workflow Status

Tamamlanan workflow bileşenleri:

* AI structured parser
* normalization layer
* customer memory recognition
* customer memory enrichment
* missing information engine
* equipment decision engine
* operational risk engine
* supplier selection workflow
* clarification gate
* management review gate
* quote generation gate
* action recommendation engine
* customer memory maintenance workflow

---

## 30. Next Workflow Priorities

Sonraki workflow geliştirme alanları:

* route-based supplier priority
* cost breakdown workflow
* margin approval workflow
* supplier quote comparison workflow
* customer-specific quote behavior
* booking workflow
* document control workflow


## Supplier Capability Matrix Data Source

Supplier Selection Engine, supplier adaylarını belirlerken supplier capability datasını kullanır.

İlk versiyonda bu data aşağıdaki JSON dosyasından okunur:

```text
data/supplier_capabilities.json
```

Bu yapı, supplier seçim mantığını kod içindeki sabit listeden ayırmak için oluşturulmuştur.

### Data Fields

Supplier capability datası şu alanları içerir:

```text
- supplier_name
- active
- role
- route_regions
- countries
- service_types
- equipment_types
- special_capabilities
- priority_routes
- reliability_score
- price_score
- speed_score
- notes
```

### Workflow Usage

Supplier Selection Step sırasında sistem:

```text
1. Shipment datasını okur
2. Equipment decision sonucunu okur
3. Risk assessment sonucunu okur
4. Supplier capability datasını yükler
5. Route, ekipman, servis tipi ve risk uygunluğuna göre supplier adaylarını skorlar
6. En fazla 3 supplier adayı önerir
```

### Current Limitation

Bu yapı şu anda demo JSON datası ile çalışır.

Gerçek ürün aşamasında supplier capability datası:

```text
- database tablosuna
- kullanıcı tarafından yönetilen supplier ekranına
- route capability matrix yapısına
- supplier performance history modeline
```

dönüştürülebilir.

### Safety Note

Kritik operasyonel sinyaller için yalnızca AI parser çıktısına güvenilmez.

ADR Class 1 ve ADR Class 7 gibi yüksek riskli ifadeler ham email metni üzerinden ayrıca kontrol edilir.
