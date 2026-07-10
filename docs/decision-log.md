# MINAI Freight OS

# Decision Log v1

## DEC-001

İlk ürün Road Freight olacaktır.

## DEC-002

RFQ maksimum 3 tedarikçiye gönderilecektir.

## DEC-003

Varsayılan araç tipi Tenteli (Curtainsider) olacaktır.

## DEC-004

Kod geliştirmeden önce Shipment Data Model oluşturulacaktır.

## DEC-005

Shipment Data Model iki seviyeli olacaktır:

* Pricing Required Fields
* Operational Fields

## DEC-006

Road Freight ilk fiyat çalışmasında Incoterm zorunlu alan değildir.

Müşteri belirtirse işlenir.
Belirtmezse fiyat çalışması durdurulmaz.

## DEC-007

Road Freight'te sistem önce FTL (Komple) / LTL (Parsiyel) ayrımı yapacaktır.

Müşteri özel olarak parsiyel istemedikçe varsayılan servis tipi FTL olacaktır.

## DEC-008

Road Freight v1 sisteminde Standard Trailer Profile kullanılacaktır.

Standard Tenteli:

* 13.60 metre
* 33 Euro Palet
* 90 m³

Commercial Weight Reference:

* 40 ton

## DEC-009

Equipment Selection Engine Road Freight v1'in çekirdek modüllerinden biri olacaktır.

## DEC-010

Customer Memory sistemi CRM gibi çalışmayacaktır.

Amaç müşteri kartı tutmak değil,
operasyonel varsayımlar üretmektir.

## DEC-011

Supplier Selection Engine minimum fiyat optimizasyonu yapmayacaktır.

Amaç:
Tecrübeli operasyon personelinin tedarikçi seçme davranışını modellemektir.

## DEC-012

Supplier Intelligence Model ilişki (relationship) faktörlerini içerecektir.

Fiyat tek başına karar kriteri değildir.

## DEC-013

Risk Assessment Engine teknik risk motoru değil,
Operational Risk Engine olacaktır.

## DEC-014

MINAI hiçbir zaman koşulsuz tam otonom davranmayacaktır.

Risk seviyesine göre:

* Green
* Yellow
* Red

karar seviyeleri uygulanacaktır.

## DEC-015

Customer Intelligence sistemi müşteri davranışını (Operational DNA) modelleyecektir.

Müşteri bilgileri sadece statik bilgilerden oluşmayacaktır.

## DEC-016

Supplier Intelligence sistemi üç ayrı boyutta değerlendirme yapacaktır:

* Operational Score
* Commercial Score
* Relationship Score

## DEC-017

Riskli operasyonlarda AI teklif hazırlayabilir ancak karar yetkisini yükseltir.

Bazı işlemler:

* Operasyon onayı
* Yönetici onayı
* Yönetim onayı

gerektirebilir.

## DEC-018

Ürün geliştirme sürecinde önce:

1. Domain Knowledge
2. Rules
3. Data Model
4. Workflow
5. Kod

sıralaması takip edilecektir.


Kod geliştirme, bilgi modelinden sonra yapılacaktır.


## DEC-019
Customer = Company

Contact Person ≠ Customer

## DEC-020
Public email domainleri müşteri tanımlamada company domain olarak kullanılmaz.

Örnek:
gmail.com
hotmail.com
outlook.com
yahoo.com
icloud.com

## DEC-021

Customer Recognition Engine
çok katmanlı çalışacaktır.

Öncelik sırası:

1. Known Contact
2. Company Domain
3. Email Signature
4. Historical Email Context
5. Manual Assignment


## DEC-022

Knowledge Capture Phase tamamlanmıştır.

Yeni özellik ekleme geçici olarak durdurulur.

Öncelik:
Database Schema
Workflow Engine
MVP Architecture

## [DEC-023 REVISION]

Historical Pricing Intelligence MVP kapsamına dahil değildir.

Ancak gelecekte kullanılabilmesi için fiyat geçmişi sistemde saklanacaktır.

İlk sürümde geçmiş fiyatlar:

referans amaçlı
anomali tespiti amaçlı
raporlama amaçlı

kullanılabilir.

Otomatik fiyat oluşturma amacıyla kullanılmayacaktır.

## DEC-024

Yellow veya Red risk durumlarında sistem quote draft üretebilir ancak eğer risk "critical missing information" kaynaklıysa fiyat/teklif oluşturmaz.

Bu durumda clarification email hazırlanır.

## DEC-025

AI parser çıktıları doğrudan workflow'a verilmez.

Önce normalization layer üzerinden geçirilir.

Amaç:
- farklı dillerde gelen değerleri standartlaştırmak
- machine → Makine
- Turkey → Türkiye
- Germany → Almanya
- FTL / full truck / komple → FTL

gibi canonical değerlere çevirmektir.

## DEC-026 — Customer Memory Delete Policy

Customer Memory profilleri UI üzerinden fiziksel olarak silinmeyecek.

Bunun yerine active/passive mantığı kullanılacak.

Gerekçe:
- Yanlışlıkla müşteri bilgisinin silinmesini önlemek
- Geçmiş operasyon kararlarının izlenebilirliğini korumak
- İleride audit trail / değişiklik geçmişi için daha güvenli zemin oluşturmak

Kural:
- active = true olan müşteri profilleri recognition ve enrichment süreçlerinde kullanılabilir.
- active = false olan müşteri profilleri listede görünebilir ancak matching/enrichment için kullanılmaz.

DEC-027 — Reserved Customer Memory Terms

Customer Memory içinde Test, Demo, Deneme, Sample, Example, Dummy gibi generic müşteri adları veya alias değerleri aktif profil olarak kullanılmayacaktır.

Gerekçe:
- AI parser bazen belirsiz müşteri adlarını Test/Demo gibi generic değerlerle döndürebilir.
- Bu değerler Customer Memory ile eşleşirse sistem yanlışlıkla müşteriyi tanınan müşteri kabul eder.
- Bu durum risk seviyesini ve önerilen aksiyonu hatalı etkileyebilir.

Kural:
- Generic customer_name değerleri reddedilir.
- Generic alias değerleri reddedilir.
- Test amaçlı müşteri gerekiyorsa ayırt edici isim kullanılmalıdır:
  - Sandbox Customer Alpha
  - ACME Test Lojistik
  - Dummy Customer 001

## DEC-028 — Customer Memory Audit Metadata

Customer Memory profillerinde değişiklik geçmişini takip edebilmek için audit metadata tutulacaktır.

Audit alanları:

* created_at
* last_updated_at
* last_updated_by
* change_note

Gerekçe:

* Müşteri hafızasında yapılan değişikliklerin izlenebilir olması gerekir.
* Yanlış varsayım, yanlış ekipman veya yanlış müşteri eşleşmesi gibi durumlarda hangi değişikliğin ne zaman yapıldığı görülebilmelidir.
* İleride daha gelişmiş audit trail sistemi için temel oluşturur.

Kural:

* Yeni oluşturulan müşteri profillerinde created_at ve last_updated_at set edilir.
* Güncellenen profillerde last_updated_at, last_updated_by ve change_note güncellenir.
* Import / restore gibi toplu işlemler de audit alanlarını günceller.

---

## DEC-029 — Customer Memory Export / Import Safety Policy

Customer Memory verisi dışa aktarılabilir ve tekrar içe aktarılabilir olacaktır.

Ancak import işlemi doğrudan uygulanmayacaktır.

Import süreci şu sırayla çalışacaktır:

1. Import Preview
2. Backend Validation
3. Dry Run
4. Kullanıcı Onayı
5. Apply Import

Gerekçe:

* Customer Memory operasyonel kararları etkileyen kritik bir veri kaynağıdır.
* Hatalı import, müşteri tanıma ve ekipman/risk kararlarını bozabilir.
* Bu nedenle gerçek import öncesinde validasyon ve dry run zorunludur.

Kural:

* Import dosyasında profiles alanı bulunmalıdır.
* profiles alanı liste olmalıdır.
* Reserved customer name / alias değerleri engellenir.
* Duplicate customer name ve duplicate alias kontrol edilir.
* Alias conflict varsa import uygulanmaz.
* UI üzerinde checkbox confirmation olmadan import uygulanmaz.

---

## DEC-030 — Customer Memory Import Apply Policy

Customer Memory import apply işlemi mevcut veriyi tamamen silip yeniden oluşturmayacaktır.

Import davranışı:

* Mevcut müşteri profili varsa update edilir.
* Yeni müşteri profili varsa add edilir.
* Import dosyasında bulunmayan mevcut profiller korunur.

Gerekçe:

* Import işlemi bakım aracı olarak kullanılacaktır.
* Kısmi importlarda mevcut müşteri hafızasının yanlışlıkla kaybolması önlenmelidir.
* Operasyonel veri güvenliği korunmalıdır.

Kural:

* Import apply öncesi otomatik backup alınır.
* Import validation başarısızsa işlem uygulanmaz.
* Alias conflict varsa işlem uygulanmaz.
* Başarılı import sonrası added / updated raporu döner.

---

## DEC-031 — Customer Memory Backup Policy

Customer Memory üzerinde import veya restore gibi veri değiştiren işlemler yapılmadan önce otomatik backup alınacaktır.

Backup dosyaları şu klasörde tutulacaktır:

```text
data/backups/
```

Gerekçe:

* Import veya restore sırasında veri bozulursa geri dönüş yolu olmalıdır.
* Customer Memory operasyonel kararları etkilediği için geri alınabilirlik zorunludur.
* Kullanıcı hataları veya yanlış import dosyaları kalıcı veri kaybına yol açmamalıdır.

Kural:

* Import apply öncesi backup alınır.
* Restore apply öncesi mevcut canlı dosyanın backup'ı alınır.
* Backup dosyaları timestamp içerecek şekilde adlandırılır.
* Backup dosyaları UI üzerinden listelenebilir.

---

## DEC-032 — Customer Memory Restore Policy

Customer Memory restore işlemi sadece sistem tarafından oluşturulmuş backup dosyalarından yapılacaktır.

Restore süreci:

1. Backup listesi görüntülenir.
2. Seçilen backup preview edilir.
3. Restore dry run çalıştırılır.
4. Alias conflict kontrol edilir.
5. Kullanıcı checkbox ile onay verir.
6. Mevcut canlı customer_memory.json için yeni backup alınır.
7. Seçilen backup canlı dosyanın yerine yazılır.

Gerekçe:

* Restore işlemi yüksek etkili bir veri operasyonudur.
* Yanlış backup seçimi veya hatalı veri dosyası sistemin müşteri tanıma davranışını bozabilir.
* Restore öncesi dry run ve confirmation zorunlu olmalıdır.

Kural:

* Restore sadece data/backups içindeki dosyalardan yapılır.
* Alias conflict varsa restore engellenir.
* Validation başarısızsa restore engellenir.
* Restore öncesi mevcut customer_memory.json yeniden yedeklenir.

---

## DEC-033 — Customer Memory Backup Cleanup Policy

Customer Memory backup dosyaları sonsuza kadar büyümeyecek şekilde yönetilecektir.

İlk cleanup politikası:

```text
Son N backup saklanır.
Daha eski backup dosyaları cleanup candidate olarak gösterilir.
```

Varsayılan değer:

```text
keep_latest = 10
```

Gerekçe:

* Backup klasörü zaman içinde kontrolsüz büyümemelidir.
* Silme işlemi riskli olduğu için önce cleanup preview gösterilmelidir.
* Sadece preview tarafından aday gösterilen eski dosyalar silinebilir.

Kural:

* Backup cleanup önce preview üretir.
* Cleanup apply kullanıcı onayı olmadan çalışmaz.
* Son N backup korunur.
* Sadece cleanup candidate dosyalar silinir.
* Silinen ve silinemeyen dosyalar raporlanır.

---

## DEC-034 — API Endpoint Order Policy

FastAPI içinde sabit endpointler, dinamik path endpointlerinden önce tanımlanacaktır.

Örnek:

```text
/customer-memory/backups/cleanup-preview
```

şu endpointten önce gelmelidir:

```text
/customer-memory/backups/{file_name}
```

Gerekçe:

* FastAPI route eşleşmesinde dinamik path endpointleri sabit endpointleri yakalayabilir.
* cleanup-preview gibi sabit path değerleri yanlışlıkla file_name gibi algılanabilir.
* Bu durum 404 veya 500 hatalarına neden olabilir.

Kural:

* Önce sabit route'lar yazılır.
* Sonra dinamik route'lar yazılır.
* Hatalı backup dosya adlarında 500 yerine uygun HTTPException döndürülür.

 ## DEC-035 — Supplier Selection Engine v1

**Status:** Accepted
**Date:** 2026-06-15

### Decision

MINAI Freight OS içine ilk versiyon Supplier Selection Engine eklenmiştir.

Sistem artık teklif sürecinde doğrudan demo supplier fiyatına geçmeden önce, talebe uygun tedarikçileri seçer ve seçim gerekçelerini üretir.

Supplier seçimi şu kriterlere göre yapılır:

* Route uygunluğu
* Ekipman uygunluğu
* Servis tipi uygunluğu
* Risk seviyesi
* Güvenilirlik skoru
* Fiyat skoru
* Hız skoru

### Rationale

Freight forwarding operasyonlarında doğru tedarikçi seçimi sadece en ucuz fiyatla yapılamaz. Hatta uygunluk, ekipman kabiliyeti, yük riski, geçmiş güvenilirlik ve hız gibi operasyonel faktörler de dikkate alınmalıdır.

Bu nedenle sistemde supplier selection ayrı bir karar katmanı olarak konumlandırılmıştır.

### Implementation

Yeni dosya:

```text
src/core/supplier_selection.py
```

Pipeline bağlantısı:

```text
Email → Shipment Parsing → Customer Memory → Missing Info → Equipment Decision → Risk Assessment → Supplier Selection → Supplier Quote → Customer Quote → Quote Draft
```

API response içine `supplier_selection` alanı eklenmiştir.

UI tarafında Supplier Selection sonucu görünür hale getirilmiştir.

### Consequences

* Sistem artık seçilen supplier adaylarını gerekçeleriyle birlikte gösterebilir.
* Supplier seçimi ileride gerçek supplier database, route capability, geçmiş performans ve müşteri ilişkisi skorlarıyla geliştirilebilir.
* Mevcut v1 demo supplier listesi ile çalışır; gerçek operasyon verisi henüz bağlı değildir.

## DEC-036 — Supplier Capability Matrix v1

**Status:** Accepted
**Date:** 2026-06-15

### Decision

Supplier Selection Engine için supplier kabiliyet verileri kod içindeki sabit listeden çıkarılmış ve ayrı bir JSON veri kaynağına taşınmıştır.

Yeni veri kaynağı:

```text
data/supplier_capabilities.json
```

Supplier Selection Engine artık supplier profillerini bu dosyadan okuyarak çalışır.

### Rationale

Supplier kabiliyetleri ürün kodunun içine gömülü kalmamalıdır. Route, ekipman, servis tipi, özel kabiliyet, güvenilirlik, fiyat ve hız skorları ileride operasyon ekibi tarafından yönetilebilir veri alanları haline gelmelidir.

Bu ayrım, sistemi gerçek supplier database / route capability matrix yapısına hazırlamak için yapılmıştır.

### Implementation

Güncellenen modül:

```text
src/core/supplier_selection.py
```

Yeni veri dosyası:

```text
data/supplier_capabilities.json
```

Supplier profilleri şu bilgileri içerir:

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

### Consequences

* Supplier selection verisi artık koddan ayrılmıştır.
* Yeni supplier eklemek için ileride kod değişikliği gerekmeyebilir.
* Gerçek ürün aşamasında bu JSON yapısı database tablosuna dönüşebilir.
* Mevcut versiyon hâlâ demo veri ile çalışır.

## DEC-037 — Supplier Selection Regression Checks

**Status:** Accepted
**Date:** 2026-06-16

### Decision

Supplier Selection Engine için regression test kontrolleri eklenmiştir.

Sistem artık yalnızca teklif üretimini değil, supplier selection ile supplier quote çıktısının birbiriyle tutarlı olup olmadığını da kontrol eder.

Özellikle şu kural test suite içine alınmıştır:

```text
Supplier Selection tarafından seçilen ilk supplier ile
Supplier Quote içinde görünen supplier aynı olmalıdır.
```

### Rationale

Supplier Selection Engine bir tedarikçi seçtiği halde, Supplier Quote çıktısında farklı bir supplier adı görünmesi operasyonel olarak tutarsızdır.

Örnek yanlış çıktı:

```text
Supplier Selection: Anatolia Domestic
Supplier Quote: Demo Transport
```

Bu durum demo/simülasyon ortamında bile kullanıcı güvenini zedeler. Sistem kendi içinde tutarlı görünmelidir.

Bu nedenle Test 7 ve Test 8 için supplier selection regression kontrolü eklenmiştir.

### Implementation

Güncellenen dosyalar:

```text
src/simulation/ai_email_test_cases.py
src/simulation/test_reporter.py
```

Test case içine `expected_supplier_name` alanı eklenmiştir.

Test reporter artık şu kontrolleri yapar:

```text
1. selected_suppliers[0].supplier_name beklenen supplier mı?
2. supplier_quote.supplier_name beklenen supplier mı?
```

### Consequences

* Supplier Selection ve Supplier Quote çıktıları arasındaki tutarsızlıklar otomatik testte yakalanır.
* Yurtiçi Oğuz Gıda testlerinde `Anatolia Domestic` supplier beklentisi doğrulanır.
* Test suite artık yalnızca teknik akışı değil, temel operasyonel tutarlılığı da kontrol etmeye başlamıştır.
* Bu karar, ileride Operational Consistency Checks yapısının temelini oluşturur.

## DEC-038 — Operational Consistency Checks v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

Operational Consistency Check yapısı eklenmiştir.

Bu yapı, workflow teknik olarak çalışsa bile lojistik açıdan bariz tutarsızlıkları yakalamak için kullanılacaktır.

İlk versiyonda sistem şu kontrolleri yapar:

```text
1. Supplier Selection boşken Supplier Quote üretilmiş mi?
2. Supplier Selection ile Supplier Quote aynı supplier'ı mı kullanıyor?
3. Yurtiçi taşımalarda domestic supplier seçilmiş mi?
4. ADR Class 1 / Class 7 yüklerde risk seviyesi red mi?
5. ADR Class 1 / Class 7 yüklerde uygun ADR ekipmanı seçilmiş mi?
6. Reefer taşımalarda soğuk zincir supplier uygunluğu şüpheli mi?
7. LTL / parsiyel taşımalarda seçilen supplier gerçekten LTL destekliyor mu?
```

### Rationale

Testlerin PASS olması tek başına yeterli değildir.

Sistem, operasyonel olarak kendi içinde tutarlı çıktı üretmelidir. Örneğin bir supplier seçip başka bir supplier adına quote üretmek, teknik olarak hata vermese bile lojistik kullanıcı açısından güven kırıcıdır.

Ayrıca bazı durumlarda AI veya simülasyon akışı sonucu üretse bile sistemin şu tür uyarılar verebilmesi gerekir:

```text
Bu taşıma LTL görünüyor, fakat seçilen supplier'ın LTL desteği capability datasında doğrulanamadı.
```

Bu nedenle operasyonel tutarlılık kontrolleri ayrı bir engine olarak tasarlanmıştır.

### Implementation

Yeni dosya eklendi:

```text
src/core/operational_consistency.py
```

Pipeline içine bağlandı:

```text
src/workflow/pipeline.py
```

Operational Consistency Engine şu kaynağı kullanır:

```text
data/supplier_capabilities.json
```

Özellikle LTL kontrolü supplier adına veya açıklama metnine bakarak değil, supplier capability datasına bakarak yapılır.

Örnek doğru yaklaşım:

```text
Shipment service_type = LTL
Selected supplier = Local LTL Network
Supplier capability service_types contains LTL
Result = no warning
```

### Consequences

* Workflow çıktılarında operasyonel tutarlılık kontrolü başlamıştır.
* Supplier Selection ve Supplier Quote arasındaki uyumsuzluklar daha erken yakalanabilir.
* LTL uygunluk kontrolü gerçek supplier capability datasına bağlanmıştır.
* İlk versiyon workflow'u durdurmaz; sadece `warnings` ve `errors` üretir.
* İleride bazı kritik hatalar workflow'u durduracak blocking validation seviyesine yükseltilebilir.

## DEC-039 — Commodity Safety Overrides v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

Commodity Safety Overrides yapısı eklenmiştir.

Bu yapı, müşteri mailinde açıkça görünen ürün ifadelerinin AI parser tarafından daha genel veya yanlış commodity değerlerine dönüştürülmesini engellemek için kullanılır.

İlk versiyonda şu deterministik eşleşmeler eklenmiştir:

```text
içecek / icecek / meşrubat / mesrubat  → İçecek / Meşrubat
trafo / transformatör / transformer    → Elektrik Transformatörü
tekstil / textile / kumaş              → Tekstil
makine / makina / machine              → Makine
```

### Rationale

AI parser bazen müşteri mailinde açık ürün ifadesi olmasına rağmen daha genel bir commodity üretebilir.

Örnek:

```text
Mailde: içecek
AI çıktısı: Gıda
Beklenen çıktı: İçecek / Meşrubat
```

Bu durum ekipman seçimi, customer memory, operasyonel uyarılar ve ileride belge/evrak tavsiyeleri açısından hatalı sonuçlara neden olabilir.

Bu nedenle raw email text içinde açık ve güvenilir ürün sinyalleri varsa, bu sinyaller AI çıktısının üstünde önceliğe sahip olmalıdır.

### Implementation

Güncellenen dosya:

```text
src/ai/email_parser.py
```

Commodity override kuralları `_apply_email_text_safety_overrides` akışı içine eklenmiştir.

Ayrıca sıcaklık kontrollü yüklerin risk değerlendirmesinde `yellow` seviyesine çıkması için risk engine güncellenmiştir.

Güncellenen dosya:

```text
src/core/risk.py
```

### Consequences

* Açık ürün sinyalleri daha tutarlı commodity değerlerine dönüştürülür.
* Oğuz Gıda / içecek senaryolarında `Gıda` yerine `İçecek / Meşrubat` çıktısı üretilir.
* Trafo / transformatör içeren maillerde `Elektrik Transformatörü` çıktısı güçlendirilir.
* Sıcaklık kontrollü yükler artık otomatik olarak human review gerektirir.
* Bu yapı MVP için kod içi güvenlik katmanıdır; ileride commodity sözlüğü ayrı data kaynağına veya database’e taşınmalıdır.

## DEC-040 — GTIP / HS Code Parser v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

GTIP / HS Code Parser v1 eklenmiştir.

MINAI artık müşteri mailinde açıkça verilen GTİP / HS kodlarını yakalayabilir, normalize edebilir ve operasyonel commodity sınıflandırmasına bağlayabilir.

Örnek:

```text
GTİP: 2202.10.00.00.00
```

Sistem bunu şu şekilde yorumlar:

```text
gtip_code: 220210000000
hs_chapter: 22
hs_heading: 2202
hs_subheading: 220210
commodity: İçecek / Meşrubat
```

### Rationale

Bazı müşteriler teklif talebi sırasında GTİP kodu paylaşabilir.

Bu durumda MINAI’nin GTİP kodunu görmezden gelmesi doğru değildir. GTİP kodu, ürün ailesini ve operasyonel commodity grubunu anlamak için güçlü bir sinyaldir.

Ancak MINAI kesin GTİP tayini yapmamalıdır. GTİP tayini hukuki ve teknik bir sınıflandırma işidir. MINAI yalnızca müşteri tarafından verilen kodu operasyonel amaçla yorumlar.

### Implementation

Yeni dosyalar:

```text
src/core/gtip.py
data/hs_commodity_map.json
```

Güncellenen dosyalar:

```text
src/core/models.py
src/ai/email_parser.py
src/simulation/ai_email_test_cases.py
src/simulation/test_reporter.py
```

Shipment modeline şu alanlar eklenmiştir:

```text
gtip_code
hs_chapter
hs_heading
hs_subheading
gtip_detected_from_email
```

Test suite içine yeni GTİP test case eklenmiştir:

```text
AI TEST 11 — GTIP beverage classification
```

### Consequences

* Müşteri mailinde verilen GTİP kodları artık shipment içine işlenir.
* GTİP kodu üzerinden operasyonel commodity güçlendirilebilir.
* 2202 kodu İçecek / Meşrubat grubuna bağlanmıştır.
* 8504 kodu Elektrik Transformatörü grubuna bağlanmıştır.
* Test suite 10 testten 11 teste çıkmıştır.
* MINAI hâlâ kesin GTİP tayini yapmaz; yalnızca müşteri tarafından verilen kodu yorumlar.

## DEC-041 — GTIP / Commodity Consistency Check v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

GTIP / Commodity Consistency Check v1 eklenmiştir.

MINAI artık müşteri mailinde verilen GTİP / HS kodu ile maildeki ürün açıklaması arasında bariz uyumsuzluk varsa bunu operasyonel uyarı olarak işaretler.

Örnek uyumsuzluk:

```text
Ürün açıklaması: plastik poşet
GTİP: 8504.21.00.00.00
```

Bu durumda sistem GTİP koduna göre ürünü körlemesine `Elektrik Transformatörü` olarak değiştirmez. Maildeki açık ürün sinyalini korur ve operational consistency warning üretir.

### Rationale

GTİP kodu güçlü bir ürün sinyalidir, ancak müşteri tarafından hatalı yazılmış olabilir.

MINAI, müşteri tarafından verilen GTİP kodunu operasyonel amaçla yorumlamalıdır; fakat ürün açıklaması ile GTİP kodu açıkça çelişiyorsa sessizce karar vermemelidir.

Bu kontrol özellikle şu hataları yakalamak için önemlidir:

```text
Ürün açıklaması: plastik poşet
GTİP kodu: elektrik transformatörü / elektrik ekipmanı grubuna ait
```

Bu tür durumlarda doğrulama gerekir.

### Implementation

Güncellenen dosyalar:

```text
src/ai/email_parser.py
src/core/operational_consistency.py
src/simulation/ai_email_test_cases.py
src/simulation/test_reporter.py
```

Test suite içine yeni test eklenmiştir:

```text
AI TEST 12 — GTIP commodity conflict warning
```

Bu testte sistem şu davranışı doğrular:

```text
Email commodity: Plastik Ürünler
GTIP commodity: Elektrik Transformatörü
Operational warning: GTIP kodu ile ürün açıklaması uyumsuz görünüyor.
```

### Consequences

* GTİP kodu ile ürün açıklaması çeliştiğinde sistem uyarı üretir.
* Maildeki açık ürün açıklaması korunur.
* GTİP kaynaklı commodity bilgisi körlemesine uygulanmaz.
* Operational Consistency Engine daha güçlü hale gelmiştir.
* Test suite 11 testten 12 teste çıkmıştır.
## DEC-042 — Commodity Dictionary v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

Commodity keyword override yapısı kod içinden çıkarılarak ayrı bir data dosyasına taşınmıştır.

Yeni data dosyası:

```text
data/commodity_dictionary.json
```

MINAI artık müşteri mailindeki ürün kelimelerini Python kodu içindeki sabit listeye göre değil, commodity dictionary datasına göre yorumlar.

Örnek eşleşmeler:

```text
içecek / meşrubat  → İçecek / Meşrubat
trafo              → Elektrik Transformatörü
tekstil            → Tekstil
plastik / poşet    → Plastik Ürünler
makine             → Makine
```

### Rationale

Ürün tipi eşleşmeleri zaman içinde büyüyecektir.

Bu eşleşmeleri `email_parser.py` içinde sabit kod olarak tutmak sürdürülebilir değildir. Yeni ürün tipi veya alias eklemek için Python kodu değiştirmek yerine data dosyası güncellenmelidir.

Bu yapı, ileride commodity dictionary’nin database veya yönetim paneline taşınması için temel oluşturur.

### Implementation

Yeni dosya:

```text
data/commodity_dictionary.json
```

Güncellenen dosya:

```text
src/ai/email_parser.py
```

Commodity safety override akışı artık `data/commodity_dictionary.json` dosyasını okuyarak çalışır.

### Consequences

* Yeni commodity alias eklemek için Python kodu değiştirmek gerekmez.
* Ürün eşleşmeleri daha yönetilebilir hale gelir.
* MVP aşamasında JSON dosyası kullanılır.
* Ürünleşme aşamasında bu yapı database tablosuna veya admin paneline taşınabilir.
* Existing parser safety behavior korunmuştur.
## DEC-043 — Commodity Dictionary Expansion v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

Commodity Dictionary v1 genişletilmiştir.

MINAI’nin MVP aşamasında daha fazla operasyonel ürün grubunu tanıyabilmesi için `data/commodity_dictionary.json` dosyasına yeni commodity grupları ve keyword alias kayıtları eklenmiştir.

Eklenen başlıca ürün grupları:

```text
Dondurulmuş Gıda
Gıda
Kimyasal Ürün
Kozmetik
Medikal Ürün
İlaç / Pharma
Elektronik
Cam / Kırılabilir
Metal Ürün
Mobilya
Ambalaj Malzemesi
Otomotiv Parçası
```

### Rationale

MVP’de ürün tanıma kabiliyeti yalnızca birkaç örnek ürünle sınırlı kalmamalıdır.

MINAI’nin operasyonel refleks gösterebilmesi için ürün gruplarını daha geniş bir sözlük üzerinden tanıması gerekir.

Bu genişleme özellikle şu alanlarda fayda sağlar:

```text
1. Ekipman seçimi
2. Risk değerlendirmesi
3. Eksik bilgi soruları
4. Belge / uygunluk uyarıları
5. Customer memory ve supplier selection kararları
```

### Implementation

Güncellenen dosya:

```text
data/commodity_dictionary.json
```

Kod mantığı değiştirilmemiştir. Parser zaten commodity dictionary datasını okuyacak şekilde çalıştığı için bu task yalnızca data genişletmesi olarak uygulanmıştır.

### Consequences

* MINAI daha fazla ürün grubunu deterministic olarak tanıyabilir.
* Yeni commodity alias ekleme süreci Python kodundan bağımsız kalmıştır.
* Test suite korunmuştur.
* Mevcut 12 test başarıyla geçmiştir.
* Commodity dictionary ileride database veya admin panel ile yönetilebilir hale getirilebilir.
## DEC-044 — Commodity Operational Profiles v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

MINAI’de commodity dictionary yalnızca ürün adı tanıyan bir yapı olmaktan çıkarılmıştır.

Belirli commodity grupları için `operational_profile` alanı eklenmiştir. Bu profil, ürün tanındığında sistemin operasyonel refleks üretmesini sağlar.

İlk versiyonda profil eklenen başlıca ürün grupları:

```text
Dondurulmuş Gıda
Kimyasal Ürün
Cam / Kırılabilir
Elektronik
Medikal Ürün
İlaç / Pharma
```

### Rationale

Freight forwarding operasyonunda ürün adı tek başına yeterli değildir.

Aynı güzergâh ve ağırlıkta iki farklı yük, ürün tipine göre tamamen farklı operasyonel dikkat gerektirebilir.

Örnek:

```text
Dondurulmuş Gıda → Reefer, sıcaklık derecesi, soğuk zincir
Kimyasal Ürün → ADR kontrolü, MSDS/SDS, ambalaj uygunluğu
Cam / Kırılabilir → ambalaj, sabitleme, hasar riski
Elektronik → yüksek değer, hırsızlık riski, hassasiyet
```

Bu nedenle MINAI’nin yalnızca commodity classification yapması yeterli görülmemiştir. Commodity tanıma sonucunda risk, ekipman ve operasyon notu üretmesi gerekir.

### Implementation

Güncellenen dosyalar:

```text
data/commodity_dictionary.json
src/core/commodity_profile.py
src/ai/email_parser.py
src/core/risk.py
src/core/equipment.py
src/simulation/ai_email_test_cases.py
```

Yeni modül:

```text
src/core/commodity_profile.py
```

Commodity profile akışı:

```text
1. Parser müşteri mailinden commodity tespit eder.
2. Commodity dictionary üzerinden ilgili operational_profile okunur.
3. Profile notları shipment.special_notes içine eklenir.
4. Gerekiyorsa risk engine human review tetikler.
5. Gerekiyorsa equipment engine özel ekipman seçer.
```

Yeni test:

```text
AI TEST 13 — Frozen food commodity profile
```

Bu testte `Dondurulmuş Gıda` yükü için sistemin `Reefer` ekipman seçmesi, risk seviyesini `yellow` yapması ve teklif akışını human review ile ilerletmesi doğrulanmıştır.

### Consequences

* MINAI ürün tipine göre operasyonel refleks vermeye başlamıştır.
* Commodity dictionary artık yalnızca alias listesi değil, operasyonel karar datası haline gelmiştir.
* Dondurulmuş gıda gibi ürünlerde Reefer seçimi data-driven hale gelmiştir.
* Kimyasal, medikal, pharma, elektronik ve kırılabilir ürünler için human review tetiklenebilir hale gelmiştir.
* Test suite 13 teste çıkmıştır.
* Mevcut testler korunmuştur.
## DEC-045 — Commodity Profile Driven Missing Info v1

**Status:** Accepted
**Date:** 2026-06-16

### Decision

MINAI’de commodity operational profile yapısı missing information engine’e bağlanmıştır.

Artık belirli ürün grupları, kendi operasyonel profiline göre ek eksik bilgi alanları tanımlayabilir.

İlk uygulama `Kimyasal Ürün` için yapılmıştır.

Kimyasal ürünlerde aşağıdaki bilgiler kritik eksik bilgi olarak kabul edilir:

```text
msds/sds document
adr status
chemical packaging type
```

Bu bilgiler eksikse sistem fiyat çalışmasına doğrudan devam etmez; müşteriden eksik bilgi istemek için clarification akışına geçer.

### Rationale

Bazı ürün gruplarında standart alanlar yeterli değildir.

Örneğin kimyasal ürünlerde yükleme yeri, teslimat yeri, ağırlık ve hazır tarih bilinse bile aşağıdaki bilgiler operasyonel olarak kritiktir:

```text
MSDS/SDS belgesi var mı?
Yük ADR kapsamında mı?
Ambalaj tipi ve ambalaj uygunluğu nedir?
```

Bu bilgiler netleşmeden fiyat vermek operasyonel hata, yanlış ekipman seçimi veya mevzuat riski doğurabilir.

Bu nedenle commodity profile, missing info engine’e ek eksik bilgi alanları sağlayabilmelidir.

### Implementation

Güncellenen dosyalar:

```text
data/commodity_dictionary.json
src/core/missing_info.py
src/ai/clarification_generator.py
src/simulation/ai_email_test_cases.py
```

`Kimyasal Ürün` operational profile içine şu alanlar eklenmiştir:

```text
missing_info_fields
critical_missing_info_fields
missing_info_reason
```

Clarification generator müşteri dostu çevirilerle aşağıdaki alanları mail taslağına ekleyebilir:

```text
MSDS/SDS belgesi
Yükün ADR kapsamında olup olmadığı
Kimyasal ürünün ambalaj tipi ve ambalaj uygunluğu
```

Yeni test:

```text
AI TEST 14 — Chemical commodity profile missing info
```

Bu testte kimyasal ürün talebi için sistemin clarification akışına geçmesi ve commodity profile kaynaklı eksik bilgileri istemesi doğrulanmıştır.

### Consequences

* Commodity profile artık yalnızca risk ve ekipman kararını değil, eksik bilgi kararını da etkiler.
* Kimyasal ürünlerde kritik bilgiler netleşmeden fiyat çalışması durdurulur.
* Clarification maili ürün tipine göre daha akıllı hale gelir.
* Test suite 14 teste çıkmıştır.
* Mevcut testler korunmuştur.
## DEC-046 — Commodity Missing Info Expansion v1

**Status:** Accepted
**Date:** 2026-07-02

### Decision

Commodity profile driven missing information yapısı genişletilmiştir.

Kimyasal ürün için başlatılan profile-driven missing info yaklaşımı, daha yüksek operasyonel hassasiyet taşıyan ürün gruplarına genişletilmiştir.

Genişletilen başlıca ürün grupları:

```text
Dondurulmuş Gıda
İlaç / Pharma
Medikal Ürün
Cam / Kırılabilir
Elektronik
```

İlk regression testi `İlaç / Pharma` ürünü için eklenmiştir.

İlaç / Pharma yüklerinde aşağıdaki bilgiler kritik eksik bilgi olarak kabul edilir:

```text
pharma temperature requirement
pharma compliance document
pharma special transport requirements
```

Bu bilgiler eksikse sistem fiyat çalışmasına doğrudan devam etmez; clarification akışına geçer.

### Rationale

Bazı ürün gruplarında standart navlun bilgileri fiyat çalışması için yeterli değildir.

Örneğin ilaç / pharma yüklerinde aşağıdaki bilgiler operasyonel olarak kritiktir:

```text
Sıcaklık gereksinimi nedir?
Uygunluk / ruhsat belgeleri var mı?
Özel taşıma şartı var mı?
```

Bu bilgiler netleşmeden teklif üretmek yanlış ekipman, yanlış fiyat, mevzuat riski veya operasyonel hasar riski doğurabilir.

Bu nedenle high-sensitivity commodity grupları, kendi profile’ları üzerinden kritik eksik bilgi alanları tanımlayabilmelidir.

### Implementation

Güncellenen dosyalar:

```text
data/commodity_dictionary.json
src/ai/clarification_generator.py
src/simulation/ai_email_test_cases.py
```

`data/commodity_dictionary.json` içinde bazı commodity profile kayıtlarına şu alanlar eklenmiştir:

```text
missing_info_fields
critical_missing_info_fields
missing_info_reason
```

Clarification generator yeni missing info alanlarını müşteri dostu Türkçe metinlere çevirecek şekilde genişletilmiştir.

Yeni test:

```text
AI TEST 15 — Pharma commodity profile missing info
```

Bu testte pharma / ilaç yükü için sistemin clarification akışına geçmesi ve ürün grubuna özel kritik bilgileri istemesi doğrulanmıştır.

### Consequences

* Commodity profile missing info yapısı tek bir ürün grubuna bağlı kalmamıştır.
* High-sensitivity commodity grupları için ürün tipine özel eksik bilgi soruları desteklenmiştir.
* İlaç / Pharma yüklerinde kritik bilgiler netleşmeden fiyat çalışması durdurulur.
* Clarification maili ürün tipine göre daha operasyonel hale gelmiştir.
* Test suite 15 teste çıkmıştır.
* Mevcut testler korunmuştur.
## DEC-047 — Commodity Profile Action Checklists v1

**Status:** Accepted
**Date:** 2026-07-02

### Decision

Commodity operational profile yapısı action recommendation checklist akışına bağlanmıştır.

MINAI artık belirli ürün grupları için operasyoncuya yalnızca genel checklist vermez; ürün tipine özel kontrol maddelerini de action recommendation içine ekler.

İlk uygulamada şu commodity grupları için `action_checklist` alanı desteklenmiştir:

```text
Kimyasal Ürün
İlaç / Pharma
Dondurulmuş Gıda
Cam / Kırılabilir
Elektronik
Medikal Ürün
```

Örnek:

```text
İlaç / Pharma:
- Sıcaklık gereksinimini müşteriyle doğrula.
- Uygunluk / ruhsat belgelerini kontrol et.
- Özel taşıma şartlarını netleştir.
```

### Rationale

Operasyoncuya verilen aksiyon önerileri yalnızca genel maddelerden oluşursa ürün bazlı riskler gözden kaçabilir.

Örneğin pharma yükünde “eksik bilgi mail taslağını kontrol et” genel bir yönlendirmedir; fakat operasyonel olarak yeterli değildir. Sistem ayrıca sıcaklık gereksinimi, belge gerekliliği ve özel taşıma şartlarını da checklist’e eklemelidir.

Bu nedenle commodity profile, action recommendation checklist’ini genişletebilmelidir.

### Implementation

Güncellenen dosyalar:

```text
data/commodity_dictionary.json
src/core/commodity_profile.py
src/core/action_recommendation.py
src/simulation/test_reporter.py
src/simulation/ai_email_test_cases.py
```

Yeni helper:

```text
get_commodity_action_checklist
```

Action recommendation akışında commodity profile’dan gelen checklist maddeleri mevcut genel checklist’e eklenir.

Test reporter, beklenen checklist maddelerini doğrulayabilecek şekilde genişletilmiştir.

Mevcut pharma regression testine action checklist beklentileri eklenmiştir.

### Consequences

* Operasyoncuya verilen aksiyon önerileri ürün tipine göre daha anlamlı hale gelmiştir.
* Commodity profile artık risk, ekipman, eksik bilgi ve aksiyon checklist kararlarını etkileyebilir.
* Pharma yükleri için sıcaklık, belge ve özel taşıma şartları checklist’e otomatik eklenir.
* Mevcut test sayısı korunmuştur.
* Test suite 15 test ile başarılı çalışmıştır.
## DEC-048 — UI Action Recommendation Checklist Display v1

**Status:** Accepted
**Date:** 2026-07-02

### Decision

MINAI Streamlit UI içinde action recommendation ve operasyonel kontrol maddelerinin görünürlüğü iyileştirilmiştir.

UI artık action checklist’i daha belirgin şekilde gösterir ve checklist’in genel operasyon maddeleri ile commodity profile kaynaklı ürün özel kontrollerini birlikte içerdiğini açıklar.

Ayrıca eksik bilgi alanları internal field code olarak değil, operasyoncu ve müşteri tarafından anlaşılır Türkçe karşılıklarla gösterilir.

### Rationale

Backend action recommendation içinde ürün tipine özel checklist maddeleri üretilse bile, UI bu bilgileri açık ve operasyonel olarak görünür sunmazsa operasyoncu önemli kontrolleri kaçırabilir.

Özellikle aşağıdaki alanların UI’da net görünmesi gerekir:

```text id="9gkr39"
Aksiyon tipi
Öncelik
Operasyon kontrol listesi
Commodity-specific checklist maddeleri
Risk nedenleri
Eksik bilgi alanları
Missing info reason
```

Bu nedenle UI, backend’in ürettiği operasyonel kararları sadece teknik JSON olarak değil, operasyoncuya doğrudan aksiyon aldıracak şekilde göstermelidir.

### Implementation

Güncellenen dosya:

```text id="wrjexa"
ui/app.py
```

Eklenen / iyileştirilen UI davranışları:

```text id="cgjxv8"
1. Eksik bilgi alanları Türkçe gösterilir.
2. Missing info reason UI’da warning olarak gösterilir.
3. Action checklist bölümü "Operasyon Kontrol Listesi" olarak güçlendirilmiştir.
4. Checklist madde sayısı gösterilir.
5. Risk nedenleri bölümüne açıklayıcı caption eklenmiştir.
6. Commodity profile kaynaklı checklist maddelerinin UI’da görünürlüğü artırılmıştır.
```

### Consequences

* Operasyoncu eksik bilgi alanlarını daha anlaşılır görür.
* Commodity-specific action checklist maddeleri UI’da daha görünür hale gelir.
* Backend’in ürettiği operasyonel refleksler kullanıcı ekranında daha iyi karşılık bulur.
* Test suite 15 test ile başarılı çalışmıştır.
## DEC-049 — UI Commodity Profile Panel v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

MINAI API response içine `commodity_profile` alanı eklenmiştir ve Streamlit UI’da ayrı bir **Commodity Profile / Operasyonel Profil** paneli gösterilmeye başlanmıştır.

Bu panel, shipment’ın ürün grubuna bağlı operasyonel profilini kullanıcıya açık şekilde gösterir.

Panelde gösterilen başlıca bilgiler:

```text
Ürün profili
Human review gerekip gerekmediği
Reefer gerekip gerekmediği
High value adayı olup olmadığı
Varsayılan ekipman / sıcaklık bilgisi
Risk profili
Operasyon notları
Profile kaynaklı eksik bilgiler
Profile action checklist
```

### Rationale

Commodity profile artık yalnızca backend karar datası değildir.

Bu profil risk, ekipman, eksik bilgi ve action checklist kararlarını etkilediği için operasyoncunun UI üzerinde bu bilgiyi doğrudan görebilmesi gerekir.

Aksi durumda sistem doğru karar üretse bile operasyoncu bu kararın ürün profili kaynaklı olduğunu anlamayabilir.

Örnek:

```text
İlaç / Pharma
→ Human review gerekli
→ Sıcaklık gereksinimi sorulmalı
→ Uygunluk / ruhsat belgeleri kontrol edilmeli
→ Özel taşıma şartları netleştirilmeli
```

Bu bilgiler tek bir panelde görünür olmalıdır.

### Implementation

Güncellenen dosyalar:

```text
src/api.py
ui/app.py
```

API tarafında `serialize_result` çıktısına `commodity_profile` eklenmiştir.

UI tarafında yeni render fonksiyonu eklenmiştir:

```text
render_commodity_profile
```

Bu fonksiyon operasyon özetinde customer memory ve action recommendation bölümlerinden önce commodity profile bilgisini gösterir.

### Consequences

* Operasyoncu ürün bazlı profil bilgisini UI’da doğrudan görebilir.
* Commodity profile kaynaklı risk, eksik bilgi ve checklist maddeleri daha anlaşılır hale gelir.
* Backend kararlarının nedeni UI’da daha şeffaf görünür.
* Test suite 15 test ile başarılı çalışmıştır.
## DEC-050 — Commodity Profile API Regression Test v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Commodity profile bilgisinin API response ve test suite içinde regression kontrolü yapılmasına karar verilmiştir.

MINAI artık API response içinde `commodity_profile` alanını döndürmektedir. Bu alan UI için kritik olduğu için test suite içinde doğrulanmalıdır.

İlk regression kontrolü `İlaç / Pharma` senaryosu üzerinde yapılmıştır.

Kontrol edilen başlıca alanlar:

```text
commodity_profile
operational_profile.risk_reason
operational_profile.missing_info_fields
operational_profile.critical_missing_info_fields
operational_profile.action_checklist
```

### Rationale

Commodity profile artık yalnızca backend içi yardımcı data değildir.

Bu yapı UI’da operasyonel profil panelini besler ve şu alanlarda karar üretir:

```text
Risk
Missing info
Action checklist
Operational notes
UI açıklamaları
```

Bu nedenle API response içinden yanlışlıkla çıkarılması veya eksik dönmesi UI davranışını bozabilir.

Bu alanın test suite ile korunması gerekir.

### Implementation

Güncellenen dosyalar:

```text
src/workflow/pipeline.py
src/api.py
src/simulation/test_reporter.py
src/simulation/ai_email_test_cases.py
```

Workflow result içine `commodity_profile` eklenmiştir.

API `serialize_result` fonksiyonu result içindeki `commodity_profile` bilgisini response’a ekler.

Test reporter aşağıdaki beklentileri kontrol edebilecek şekilde genişletilmiştir:

```text
commodity_profile
commodity_profile_keys
commodity_profile_missing_fields
commodity_profile_action_checklist_contains
```

Pharma regression testine commodity profile beklentileri eklenmiştir.

### Consequences

* API response içindeki commodity profile datası regression test ile korunur.
* UI için kritik operasyonel profil datasının kaybolması testlerde yakalanır.
* Commodity profile panelinin backend kontratı daha güvenli hale gelir.
* Test suite 15 test ile başarılı çalışmıştır.
## DEC-051 — Operational Profile Data Hygiene v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Commodity dictionary ve operational profile datası için otomatik validation mekanizması eklenmiştir.

Yeni validator:

```text id="nnv9zd"
src/core/commodity_dictionary_validator.py
```

Validator, `data/commodity_dictionary.json` dosyasının yapısal olarak doğru kalmasını kontrol eder.

İlk validation kapsamı:

```text id="a6uamw"
canonical_commodity boş olamaz.
keywords liste olmalı ve boş olmamalıdır.
Aynı commodity içinde duplicate keyword olmamalıdır.
Genel dictionary içinde duplicate keyword uyarı olarak raporlanır.
notes varsa liste olmalıdır.
operational_profile varsa object / dict olmalıdır.
missing_info_fields liste olmalıdır.
critical_missing_info_fields liste olmalıdır.
critical_missing_info_fields içindeki her alan missing_info_fields içinde de bulunmalıdır.
action_checklist liste olmalıdır.
Profile boolean alanları boolean olmalıdır.
Profile string alanları boş string olmamalıdır.
```

Validator test suite akışına bağlanmıştır.

### Rationale

Commodity dictionary artık yalnızca basit bir keyword listesi değildir.

Bu dosya şu kararları etkiler:

```text id="at8d4z"
Commodity recognition
Risk assessment
Equipment decision
Missing information
Clarification questions
Action recommendation checklist
UI commodity profile panel
```

Bu nedenle dictionary içinde yapılacak hatalı veya eksik bir kayıt, sistemin operasyonel kararlarını bozabilir.

Bu risk manuel kontrolle yönetilemez. Data büyüdükçe otomatik validation gereklidir.

### Implementation

Yeni dosya:

```text id="zrejas"
src/core/commodity_dictionary_validator.py
```

Güncellenen dosyalar:

```text id="bmmgpc"
src/simulation/test_reporter.py
src/workflow/pipeline.py
src/api.py
```

Test suite içine yeni validation testi eklenmiştir:

```text id="r6f9co"
Commodity dictionary validation
```

Bu test dictionary invalid olduğunda fail verir.

### Consequences

* Commodity dictionary veri kalitesi otomatik kontrol edilir.
* Operational profile alanlarının hatalı girilmesi testlerde yakalanır.
* UI ve backend kararları için kritik data daha güvenli hale gelir.
* Test suite 16 teste çıkmıştır.
* Mevcut operasyonel testler korunmuştur.
## DEC-052 — Commodity Dictionary Validation UI v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Commodity dictionary validation sonucunun UI üzerinden görüntülenmesine karar verilmiştir.

Yeni UI paneli:

```text
Data Sağlığı / Commodity Dictionary
```

Bu panel sadece okuma amaçlıdır.

Panel şu bilgileri gösterir:

```text
Valid / invalid durumu
Commodity sayısı
Unique keyword sayısı
Hata sayısı
Uyarı sayısı
Validation source
Hata detayları
Uyarı detayları
Raw validation result
```

API tarafına yeni endpoint eklenmiştir:

```text
GET /commodity-dictionary/validation
```

### Rationale

Commodity dictionary artık operasyonel karar datasıdır.

Bu data şu alanları etkiler:

```text
Commodity recognition
Risk assessment
Equipment decision
Missing information
Action checklist
UI commodity profile panel
```

Bu nedenle yalnızca terminal testlerinde değil, UI üzerinden de data sağlığının görülebilmesi gerekir.

Operasyoncu veya proje yöneticisi dictionary sağlığını kod açmadan kontrol edebilmelidir.

### Implementation

Güncellenen dosyalar:

```text
src/api.py
ui/app.py
```

API tarafında validator sonucu endpoint olarak açılmıştır.

UI tarafında “Data Sağlığı / Commodity Dictionary” paneli eklenmiştir.

Panel şu anda dictionary edit etmez. Sadece validator sonucunu gösterir.

### Consequences

* Commodity dictionary sağlığı UI üzerinden izlenebilir.
* Validator sonucu teknik olmayan kullanıcıya daha görünür hale gelir.
* Data health kontrolü test suite dışında da erişilebilir olur.
* Dictionary edit yetkisi bilinçli olarak eklenmemiştir.
* UI paneli read-only kalır.
## DEC-053 — Supplier Capability Matrix Validator v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Supplier capability matrix datası için otomatik validation mekanizması eklenmiştir.

Yeni validator:

```text
src/core/supplier_capability_validator.py
```

Validator, `data/supplier_capabilities.json` dosyasının yapısal olarak doğru kalmasını kontrol eder.

İlk validation kapsamı:

```text
supplier_name boş olamaz.
duplicate supplier_name olamaz.
active boolean olmalıdır.
role geçerli değerlerden biri olmalıdır.
route_regions liste olmalıdır.
countries liste olmalıdır.
service_types liste olmalıdır.
equipment_types liste olmalıdır.
special_capabilities liste olmalıdır.
priority_routes liste olmalıdır.
reliability_score sayı olmalı ve 0-1 aralığında olmalıdır.
price_score sayı olmalı ve 0-1 aralığında olmalıdır.
speed_score sayı olmalı ve 0-1 aralığında olmalıdır.
notes boş olmayan string olmalıdır.
En az bir active supplier bulunmalıdır.
En az bir active FTL supplier bulunmalıdır.
LTL, Reefer ve ADR coverage eksikliği warning olarak raporlanır.
```

Validator test suite akışına bağlanmıştır.

### Rationale

Supplier capability matrix, supplier selection engine için operasyonel karar datasıdır.

Bu dosya şu kararları etkiler:

```text
Supplier selection
Route capability
Equipment fit
Risk fit
Price / speed scoring
Quote supplier consistency
Operational consistency checks
```

Bu nedenle supplier datasında yapılacak eksik veya hatalı bir kayıt, yanlış supplier seçimine veya yanlış operasyonel uyarıya yol açabilir.

Supplier datası büyüdükçe manuel kontrol yeterli değildir. Otomatik validation gerekir.

### Implementation

Yeni dosya:

```text
src/core/supplier_capability_validator.py
```

Güncellenen dosyalar:

```text
src/simulation/test_reporter.py
src/workflow/pipeline.py
src/api.py
```

Test suite içine yeni validation testi eklenmiştir:

```text
Supplier capability validation
```

Bu test supplier capability matrix invalid olduğunda fail verir.

### Consequences

* Supplier capability matrix veri kalitesi otomatik kontrol edilir.
* Supplier selection engine için kritik data daha güvenli hale gelir.
* Eksik FTL coverage gibi kritik hatalar testlerde yakalanır.
* LTL, Reefer ve ADR coverage eksiklikleri warning olarak görülebilir.
* Test suite 17 teste çıkmıştır.
## DEC-054 — Supplier Capability Validation UI v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Supplier capability matrix validation sonucunun UI üzerinden görüntülenmesine karar verilmiştir.

Yeni UI paneli:

```text
Data Sağlığı / Supplier Capability Matrix
```

Bu panel sadece okuma amaçlıdır.

Panel şu bilgileri gösterir:

```text
Valid / invalid durumu
Supplier sayısı
Active supplier sayısı
Active FTL supplier sayısı
Active LTL supplier sayısı
Active Reefer supplier sayısı
Active ADR supplier sayısı
Hata sayısı
Uyarı sayısı
Validation source
Hata detayları
Uyarı detayları
Raw validation result
```

API tarafına yeni endpoint eklenmiştir:

```text
GET /supplier-capabilities/validation
```

### Rationale

Supplier capability matrix, supplier selection engine için kritik operasyonel data kaynağıdır.

Bu data şu alanları etkiler:

```text
Supplier selection
Route fit
Equipment fit
Risk fit
Supplier quote simulation
Operational consistency checks
UI supplier selection display
```

Bu nedenle supplier datasının sağlığı yalnızca terminal testlerinde değil, UI üzerinden de görülebilmelidir.

Operasyoncu veya proje yöneticisi supplier coverage durumunu kod açmadan kontrol edebilmelidir.

### Implementation

Güncellenen dosyalar:

```text
src/api.py
ui/app.py
```

API tarafında supplier capability validator sonucu endpoint olarak açılmıştır.

UI tarafında “Data Sağlığı / Supplier Capability Matrix” paneli eklenmiştir.

Panel şu anda supplier datasını edit etmez. Sadece validator sonucunu gösterir.

### Consequences

* Supplier capability matrix sağlığı UI üzerinden izlenebilir.
* FTL / LTL / Reefer / ADR coverage durumu görünür hale gelir.
* Supplier datasındaki hata ve uyarılar teknik olmayan kullanıcıya daha anlaşılır şekilde gösterilir.
* Data health kontrolü test suite dışında da erişilebilir olur.
* Supplier edit yetkisi bilinçli olarak eklenmemiştir.
* UI paneli read-only kalır.
## DEC-055 — Data Health Dashboard Consolidation v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

UI’daki data health kontrollerinin tek bir dashboard altında toplanmasına karar verilmiştir.

Yeni ana bölüm:

```text
Data Sağlığı Dashboard
```

Bu dashboard şu kontrolleri sekmeler halinde gösterir:

```text
Test Suite
Commodity Dictionary
Supplier Capability Matrix
```

Önceki ayrı panel yapısı sadeleştirilmiştir.

### Rationale

MINAI UI büyüdükçe data health kontrolleri sayfa içinde dağılmaya başlamıştır.

Test suite, commodity dictionary validation ve supplier capability validation aynı operasyonel amaca hizmet eder:

```text
Sistemin sağlıklı çalıştığını kontrol etmek
Kritik data kaynaklarının bozulmadığını görmek
Hata ve uyarıları operasyoncu / proje yöneticisi için görünür yapmak
```

Bu nedenle bu kontrollerin tek bir dashboard altında toplanması UI’ın okunabilirliğini artırır.

### Implementation

Güncellenen dosya:

```text
ui/app.py
```

Aşağıdaki yapı kurulmuştur:

```text
render_data_health_dashboard()
render_test_suite_runner_content()
render_commodity_dictionary_validation_content()
render_supplier_capabilities_validation_content()
```

Sayfanın altındaki ayrı çağrılar yerine tek dashboard çağrısı kullanılmaktadır:

```text
render_data_health_dashboard()
```

### Consequences

* UI daha düzenli hale gelmiştir.
* Data health kontrolleri tek bölümde toplanmıştır.
* Test suite ve validator panelleri birbirinden kopuk görünmez.
* Yeni data health kontrolleri ileride aynı dashboard’a sekme olarak eklenebilir.
* Dashboard read-only kalmıştır.
## DEC-056 — Customer Memory Validation v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Customer memory datası için otomatik validation mekanizması eklenmiştir.

Yeni validator:

```text id="e8cmf3"
src/core/customer_memory_validator.py
```

Validator, `data/customer_memory.json` dosyasının yapısal olarak doğru kalmasını kontrol eder.

İlk validation kapsamı:

```text id="hc3pne"
customer_name boş olamaz.
duplicate customer_name olamaz.
active boolean olmalıdır.
aliases liste olmalıdır.
Aynı profile içinde duplicate alias olamaz.
Aynı alias iki farklı müşteride kullanılamaz.
Alias başka bir customer_name ile çakışamaz.
price_sensitivity sadece low / medium / high / boş olabilir.
time_sensitivity sadece low / medium / high / boş olabilir.
default_equipment_type bilinen ekipman listesine göre kontrol edilir.
operational_notes liste olmalıdır.
Opsiyonel string alanları string veya null olmalıdır.
```

Validator test suite akışına bağlanmıştır.

### Rationale

Customer memory, MINAI’nin düzenli müşterileri doğru tanıması ve eksik bilgileri tekrar tekrar istememesi için kritik data kaynağıdır.

Bu data şu alanları etkiler:

```text id="lmrpic"
Customer recognition
Default commodity
Default equipment
Default pickup / delivery assumptions
Risk assessment
Missing information behavior
Customer-specific operational notes
```

Bu nedenle customer memory içinde yapılacak bozuk kayıt, duplicate alias veya geçersiz değerler yanlış müşteri eşleşmesine ve yanlış operasyonel karara yol açabilir.

Customer memory büyüdükçe manuel kontrol yeterli değildir. Otomatik validation gerekir.

### Implementation

Yeni dosya:

```text id="x6mytw"
src/core/customer_memory_validator.py
```

Güncellenen dosyalar:

```text id="vwbccj"
src/simulation/test_reporter.py
src/workflow/pipeline.py
src/api.py
```

Test suite içine yeni validation testi eklenmiştir:

```text id="jzbdkq"
Customer memory validation
```

Bu test customer memory invalid olduğunda fail verir.

### Consequences

* Customer memory veri kalitesi otomatik kontrol edilir.
* Duplicate alias ve duplicate customer name riskleri testlerde yakalanır.
* Geçersiz sensitivity değerleri testlerde yakalanır.
* Yanlış müşteri eşleşmesi riski azalır.
* Test suite 18 teste çıkmıştır.
## DEC-057 — Customer Memory Validation UI v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

Customer memory validation sonucunun UI üzerinden görüntülenmesine karar verilmiştir.

Yeni UI sekmesi:

```text id="8lkvn6"
Data Sağlığı Dashboard → Customer Memory
```

Bu sekme sadece okuma amaçlıdır.

Panel şu bilgileri gösterir:

```text id="o4gh9z"
Valid / invalid durumu
Profile sayısı
Active profile sayısı
Alias sayısı
Hata sayısı
Uyarı sayısı
Validation source
Hata detayları
Uyarı detayları
Raw validation result
```

API tarafına yeni endpoint eklenmiştir:

```text id="czl92v"
GET /customer-memory/validation
```

### Rationale

Customer memory, MINAI’nin düzenli müşterileri tanıması ve müşteri özel varsayımları uygulaması için kritik data kaynağıdır.

Bu data şu alanları etkiler:

```text id="uaev24"
Customer recognition
Alias matching
Default commodity
Default equipment
Default pickup / delivery assumptions
Risk assessment
Missing information behavior
Operational notes
```

Bu nedenle customer memory datasının sağlığı yalnızca test suite içinde değil, UI üzerinden de görülebilmelidir.

Operasyoncu veya proje yöneticisi müşteri hafızası sağlığını kod açmadan kontrol edebilmelidir.

### Implementation

Güncellenen dosyalar:

```text id="i2mpmo"
src/api.py
ui/app.py
```

API tarafında customer memory validator sonucu endpoint olarak açılmıştır.

UI tarafında Data Sağlığı Dashboard içine “Customer Memory” sekmesi eklenmiştir.

Panel şu anda customer memory datasını edit etmez. Sadece validator sonucunu gösterir.

### Consequences

* Customer memory sağlığı UI üzerinden izlenebilir.
* Profile / active profile / alias sayıları görünür hale gelir.
* Duplicate alias, invalid sensitivity veya bozuk kayıtlar UI’dan görülebilir.
* Data health dashboard artık üç ana data kaynağını kapsar:

  * Commodity Dictionary
  * Supplier Capability Matrix
  * Customer Memory
* Panel read-only kalır.
## DEC-058 — HS / GTIP Mapping Validator v1

**Status:** Accepted
**Date:** 2026-07-03

### Decision

HS / GTIP commodity mapping datası için otomatik validation mekanizması eklenmiştir.

Yeni validator:

```text id="n8ubt6"
src/core/hs_commodity_map_validator.py
```

Validator, `data/hs_commodity_map.json` dosyasının yapısal olarak doğru kalmasını kontrol eder.

İlk validation kapsamı:

```text id="t2aizw"
Root yapı dict / object olmalıdır.
En az bir mapping bulunmalıdır.
HS kodları yalnızca rakamlardan oluşmalıdır.
HS kod uzunluğu 2, 4 veya 6 karakter olmalıdır.
Duplicate HS code key yakalanmalıdır.
commodity_group boş olamaz.
notes varsa liste olmalıdır.
notes içindeki her madde boş olmayan string olmalıdır.
Heading / subheading kayıtlarında parent chapter veya heading eksikse warning üretilir.
commodity_group, commodity dictionary canonical değerleriyle birebir eşleşmiyorsa warning üretilir.
```

Validator test suite akışına bağlanmıştır.

### Rationale

HS / GTIP mapping, müşterinin verdiği GTIP veya HS kodunu operasyonel commodity grubuna çevirmek için kullanılır.

Bu data şu alanları etkiler:

```text id="cm9n1d"
GTIP interpretation
Commodity classification
GTIP / commodity consistency warning
Operational notes
Risk and missing information behavior
Customer quote workflow safety
```

Bu nedenle HS / GTIP mapping içinde yapılacak bozuk kayıt, yanlış commodity yorumuna veya yanlış operasyonel uyarıya yol açabilir.

HS / GTIP datası büyüdükçe manuel kontrol yeterli değildir. Otomatik validation gerekir.

### Implementation

Yeni dosya:

```text id="u55ceu"
src/core/hs_commodity_map_validator.py
```

Güncellenen dosyalar:

```text id="6klry2"
src/simulation/test_reporter.py
src/workflow/pipeline.py
src/api.py
```

Test suite içine yeni validation testi eklenmiştir:

```text id="xn6q69"
HS / GTIP commodity map validation
```

Bu test HS / GTIP mapping invalid olduğunda fail verir.

Commodity dictionary ile birebir eşleşmeyen ama operasyonel grup olarak kullanılan commodity_group değerleri ilk sürümde hata değil warning olarak raporlanır.

### Consequences

* HS / GTIP mapping veri kalitesi otomatik kontrol edilir.
* Hatalı HS kod formatları testlerde yakalanır.
* Bozuk notes veya boş commodity_group testlerde yakalanır.
* Parent chapter / heading coverage eksiklikleri warning olarak görülebilir.
* Commodity dictionary ile birebir uyumsuz operasyonel gruplar warning olarak izlenebilir.
* Test suite 19 teste çıkmıştır.
## DEC-059 — HS / GTIP Mapping Validation UI v1

**Status:** Accepted
**Date:** 2026-07-04

### Decision

HS / GTIP mapping validation sonucunun UI üzerinden görüntülenmesine karar verilmiştir.

Yeni UI sekmesi:

```text
Data Sağlığı Dashboard → HS / GTIP Mapping
```

Bu sekme sadece okuma amaçlıdır.

Panel şu bilgileri gösterir:

```text
Valid / invalid durumu
Mapping sayısı
Chapter sayısı
Heading sayısı
Subheading sayısı
Canonical commodity sayısı
Hata sayısı
Uyarı sayısı
Validation source
Hata detayları
Uyarı detayları
Raw validation result
```

API tarafına yeni endpoint eklenmiştir:

```text
GET /hs-commodity-map/validation
```

### Rationale

HS / GTIP mapping, müşterinin verdiği GTIP veya HS kodunu operasyonel commodity grubuna çevirmek için kullanılır.

Bu data şu alanları etkiler:

```text
GTIP interpretation
Commodity classification
GTIP / commodity consistency warning
Operational notes
Risk and missing information behavior
Customer quote workflow safety
```

Bu nedenle HS / GTIP mapping datasının sağlığı yalnızca test suite içinde değil, UI üzerinden de görülebilmelidir.

Operasyoncu veya proje yöneticisi GTIP mapping sağlığını kod açmadan kontrol edebilmelidir.

### Implementation

Güncellenen dosyalar:

```text
src/api.py
ui/app.py
```

API tarafında HS / GTIP mapping validator sonucu endpoint olarak açılmıştır.

UI tarafında Data Sağlığı Dashboard içine “HS / GTIP Mapping” sekmesi eklenmiştir.

Panel şu anda HS / GTIP mapping datasını edit etmez. Sadece validator sonucunu gösterir.

### Consequences

* HS / GTIP mapping sağlığı UI üzerinden izlenebilir.
* Chapter / heading / subheading coverage durumu görünür hale gelir.
* Hatalar ve warning’ler teknik olmayan kullanıcıya daha görünür olur.
* Data Sağlığı Dashboard artık dört ana data kaynağını kapsar:

  * Commodity Dictionary
  * Supplier Capability Matrix
  * Customer Memory
  * HS / GTIP Mapping
* Panel read-only kalır.
## DEC-060 — Data Health Summary Endpoint v1

**Status:** Accepted
**Date:** 2026-07-04

### Decision

Data health validator sonuçlarının tek bir API endpoint altında toplanmasına karar verilmiştir.

Yeni endpoint:

```text id="q37e7u"
GET /data-health/summary
```

Bu endpoint şu validator sonuçlarını birlikte döndürür:

```text id="s6i18u"
commodity_dictionary
supplier_capabilities
customer_memory
hs_commodity_map
```

Endpoint ayrıca genel özet alanları üretir:

```text id="f900sc"
overall_valid
total_checks
valid_checks
invalid_checks
total_errors
total_warnings
checks
```

### Rationale

MINAI’de artık birden fazla kritik data kaynağı validator ile korunmaktadır.

Bu kaynaklar:

```text id="t9ovfc"
Commodity Dictionary
Supplier Capability Matrix
Customer Memory
HS / GTIP Mapping
```

Her biri ayrı endpoint üzerinden kontrol edilebilse de UI ve ilerideki monitoring ihtiyaçları için tek bir özet endpoint gerekir.

Bu endpoint, sistemin data sağlığını hızlıca değerlendirmek için merkezi kontrat sağlar.

### Implementation

Güncellenen dosya:

```text id="hzy3hu"
src/api.py
```

Yeni yardımcı fonksiyon eklenmiştir:

```text id="3moce1"
build_data_health_summary()
```

Yeni API endpoint eklenmiştir:

```text id="fpuniv"
GET /data-health/summary
```

### Consequences

* Tüm data health validator sonuçları tek endpoint altında görülebilir.
* UI dashboard için merkezi summary data oluşmuştur.
* Monitoring veya ilerideki otomasyonlar tek endpoint üzerinden data sağlığı kontrol edebilir.
* Mevcut ayrı validation endpoint’leri korunmuştur.
* Test suite 19 test ile başarılı çalışmıştır.
## DEC-061 — Data Health Summary UI v1

**Status:** Accepted
**Date:** 2026-07-04

### Decision

Data Sağlığı Dashboard içine genel summary kartı eklenmesine karar verilmiştir.

Yeni UI bölümü:

```text
Data Sağlığı Dashboard → Summary
```

Bu summary, yeni merkezi endpoint üzerinden data health durumunu gösterir:

```text
GET /data-health/summary
```

Summary alanları:

```text
Overall Valid
Valid Checks
Errors
Warnings
Kontrol Özeti
Raw Data Health Summary
```

### Rationale

MINAI’de birden fazla kritik data validator bulunmaktadır:

```text
Commodity Dictionary
Supplier Capability Matrix
Customer Memory
HS / GTIP Mapping
```

Ayrı sekmeler detaylı kontrol için faydalıdır, ancak kullanıcı dashboard’a girdiğinde sistemin genel data sağlığını tek bakışta görebilmelidir.

Bu nedenle dashboard üstünde merkezi bir summary alanı gerekir.

### Implementation

Güncellenen dosya:

```text
ui/app.py
```

Yeni UI fonksiyonu eklenmiştir:

```text
render_data_health_summary()
```

Bu fonksiyon `/data-health/summary` endpoint’ini çağırır ve sonucu Data Sağlığı Dashboard’un üstünde gösterir.

Summary altında her validator için kısa kontrol özeti gösterilir.

### Consequences

* Data health genel durumu tek bakışta görülebilir.
* Ayrı validator sekmelerine girmeden önce genel sağlık durumu anlaşılır.
* Error ve warning toplamları görünür hale gelir.
* Dashboard daha yönetici / PM dostu hale gelir.
* Detaylı validator panelleri korunmuştur.
## DEC-062 — Data Health Summary Refresh State v1

**Status:** Accepted
**Date:** 2026-07-05

### Decision

Data Sağlığı Dashboard içindeki summary alanına manuel refresh ve last checked bilgisi eklenmesine karar verilmiştir.

Yeni UI davranışı:

```text
Refresh Data Health Summary
Last checked: YYYY-MM-DD HH:MM:SS
```

Summary sonucu `st.session_state` içinde tutulur.

Kullanıcı dashboard’a geldiğinde summary otomatik alınır. Kullanıcı isterse “Refresh Data Health Summary” butonu ile sonucu tekrar çağırabilir.

### Rationale

Data health summary tek bakışta sistemin operasyonel data sağlığını gösterir.

Ancak kullanıcı summary’nin ne zaman kontrol edildiğini bilmezse ekrandaki bilginin güncelliğinden emin olamaz.

Bu nedenle dashboard’da son kontrol zamanı görünmelidir.

Ayrıca kullanıcı API veya data değişikliklerinden sonra sayfayı komple yenilemeden summary sonucunu manuel güncelleyebilmelidir.

### Implementation

Güncellenen dosya:

```text
ui/app.py
```

Yeni yardımcı fonksiyon eklenmiştir:

```text
fetch_data_health_summary()
```

`render_data_health_summary()` fonksiyonu güncellenmiştir.

Eklenen UI alanları:

```text
Genel Data Health Özeti
Refresh Data Health Summary
Last checked
```

Summary sonucu şu session state alanlarında tutulur:

```text
data_health_summary
data_health_summary_checked_at
```

### Consequences

* Data health summary’nin ne zaman kontrol edildiği görünür.
* Kullanıcı summary sonucunu manuel yenileyebilir.
* Dashboard daha güvenilir ve anlaşılır hale gelir.
* Detay sekmeleri ve raw summary korunmuştur.
## DEC-063 — Data Health Summary Core Service v1

**Status:** Accepted
**Date:** 2026-07-05

### Decision

Data health summary üretim mantığının API katmanından çıkarılıp core servis katmanına taşınmasına karar verilmiştir.

Yeni core servis dosyası:

```text
src/core/data_health.py
```

Yeni core fonksiyon:

```text
build_data_health_summary()
```

API endpoint aynı kalmıştır:

```text
GET /data-health/summary
```

Ancak endpoint artık summary mantığını kendi içinde üretmez; core servisten çağırır.

### Rationale

Data health summary bir API davranışı değil, operasyonel core servis mantığıdır.

API dosyasının görevi endpoint sunmak olmalıdır. Validator sonuçlarını toplamak, toplam hata / uyarı sayısını hesaplamak ve overall health üretmek core katmanda kalmalıdır.

Bu ayrım ileride test, bakım ve yeni validator ekleme süreçlerini kolaylaştırır.

### Implementation

Yeni dosya:

```text
src/core/data_health.py
```

Güncellenen dosya:

```text
src/api.py
```

`src/api.py` içindeki eski `build_data_health_summary()` fonksiyonu kaldırılmıştır.

API artık şu import üzerinden core servisi kullanır:

```text
from src.core.data_health import build_data_health_summary
```

### Consequences

* Data health summary mantığı API dışına taşındı.
* API katmanı sadeleşti.
* Core servis ileride doğrudan test edilebilir hale geldi.
* UI endpoint değişmediği için UI tarafında değişiklik gerekmedi.
* Yeni validator eklendiğinde merkezi summary mantığı `src/core/data_health.py` üzerinden yönetilecektir.
## DEC-064 — Data Health Summary Regression Test v1

**Status:** Accepted
**Date:** 2026-07-05

### Decision

Data health summary çıktısının test suite içinde regression test ile doğrulanmasına karar verilmiştir.

Yeni test:

```text id="mxcydn"
Data health summary regression
```

Test suite sonucu:

```text id="jr50ce"
20 passed, 0 failed
```

### Rationale

`/data-health/summary` endpoint’i UI için kritik bir contract üretmektedir.

Bu contract şu alanları içerir:

```text id="fnw81j"
overall_valid
total_checks
valid_checks
invalid_checks
total_errors
total_warnings
checks
```

Bu yapı bozulursa Data Sağlığı Dashboard yanlış veya eksik bilgi gösterebilir.

Bu nedenle summary response yapısı test suite içinde korunmalıdır.

### Implementation

Güncellenen dosyalar:

```text id="n1xskj"
src/simulation/test_reporter.py
src/workflow/pipeline.py
```

Yeni evaluator:

```text id="d95ks6"
evaluate_data_health_summary()
```

Test şu kontrolleri yapar:

```text id="st9axu"
Gerekli top-level summary alanları var mı?
checks dictionary mi?
Beklenen validator check isimleri var mı?
total_checks doğru mu?
valid_checks doğru hesaplanıyor mu?
invalid_checks doğru hesaplanıyor mu?
total_errors doğru hesaplanıyor mu?
total_warnings doğru hesaplanıyor mu?
overall_valid doğru hesaplanıyor mu?
```

Beklenen check isimleri:

```text id="ezthw8"
commodity_dictionary
supplier_capabilities
customer_memory
hs_commodity_map
```

### Consequences

* Data health summary response contract test altına alındı.
* UI için kritik summary alanlarının yanlışlıkla bozulması zorlaştı.
* Yeni validator eklendiğinde regression test güncellenmelidir.
* Test suite toplamı 19’dan 20’ye çıkmıştır.
## DEC-065 — Data Health Summary Warning Details UI v1

**Status:** Accepted
**Date:** 2026-07-05

### Decision

Data Sağlığı Dashboard içindeki summary alanında warning ve error detaylarının gösterilmesine karar verilmiştir.

Yeni UI bölümü:

```text id="go9a9g"
Data Health Uyarı / Hata Detayları
```

Bu bölüm, `/data-health/summary` response içindeki validator bazlı `errors` ve `warnings` listelerini gösterir.

Her validator için ayrı expander kullanılır.

### Rationale

Summary alanı toplam error ve warning sayılarını gösteriyordu.

Ancak kullanıcı uyarıların ne olduğunu görmek için detay sekmelerine tek tek girmek zorunda kalıyordu.

Bu durum özellikle şu bilgi için yetersizdi:

```text id="yl4mm3"
Warnings: 6
```

Bu nedenle summary alanında uyarı ve hata detayları hızlıca görülebilmelidir.

### Implementation

Güncellenen dosya:

```text id="88zwew"
ui/app.py
```

`render_data_health_summary()` fonksiyonu genişletilmiştir.

Eklenen davranış:

```text id="m7p6d4"
summary.checks içindeki error/warning bulunan validator’lar tespit edilir
her validator için expander oluşturulur
errors listesi ❌ ile gösterilir
warnings listesi ⚠️ ile gösterilir
error/warning yoksa bilgi mesajı gösterilir
Raw Data Health Summary korunur
```

### Consequences

* Kullanıcı toplam warning sayısının detayını summary alanında görebilir.
* Detay sekmelerine girmeden hızlı data health kontrolü yapılabilir.
* Error ve warning ayrımı daha görünür hale gelir.
* Endpoint değişmedi.
* Data Sağlığı Dashboard read-only kalmaya devam eder.
## DEC-066 — Data Health Summary Human-Friendly Labels v1

**Status:** Accepted
**Date:** 2026-07-05

### Decision

Data Sağlığı Dashboard summary alanındaki teknik / İngilizce etiketlerin kullanıcı dostu Türkçe operasyon diliyle gösterilmesine karar verilmiştir.

Yeni label örnekleri:

```text id="s0g7uf"
Refresh Data Health Summary → Özeti Yenile
Last checked → Son kontrol
Overall Valid → Genel Durum
Valid Checks → Geçen Kontrol
Errors → Hata
Warnings → Uyarı
Raw Data Health Summary → Ham Data Sağlığı Özeti
```

Validator isimleri de kullanıcı dostu hale getirilmiştir:

```text id="kzd87d"
commodity_dictionary → Ürün Sözlüğü
supplier_capabilities → Tedarikçi Yetkinlik Matrisi
customer_memory → Müşteri Hafızası
hs_commodity_map → HS / GTIP Eşleştirme
```

### Rationale

Data Sağlığı Dashboard operasyon kullanıcısı ve PM için okunabilir olmalıdır.

Teknik alan adları geliştirici için anlamlıdır, ancak kullanıcı ekranında doğrudan görünmeleri ürün deneyimini zayıflatır.

Bu nedenle UI label’ları teknik sistem adlarından ayrılmıştır.

### Implementation

Güncellenen dosya:

```text id="36x4rd"
ui/app.py
```

Yeni yardımcı fonksiyon:

```text id="5azouc"
get_data_health_check_label()
```

Bu fonksiyon data health check anahtarlarını kullanıcı dostu label’lara çevirir.

Summary alanındaki buton, metric, caption, expander ve hata/uyarı metinleri Türkçe operasyon ekranı diline yaklaştırılmıştır.

### Consequences

* Data Sağlığı Dashboard daha kullanıcı dostu hale geldi.
* Teknik check isimleri UI’da doğrudan görünmez.
* Validator key’leri API contract içinde korunur.
* UI label’ları ayrı helper üzerinden yönetilebilir hale geldi.
* Endpoint, core servis ve test suite değişmedi.

## DEC-067 — Data Health Label Mapping Contract Test v1

**Status:** Accepted  
**Date:** 2026-07-10

### Decision

Data health validator anahtarlarının kullanıcı dostu UI etiketlerine dönüştürülmesi için merkezi bir label helper kullanılmasına ve bu mapping'in regression test ile korunmasına karar verilmiştir.

Yeni core dosyası:

    src/core/data_health_labels.py

Yeni helper:

    get_data_health_check_label()

Yeni test:

    Data health label mapping

Test suite sonucu:

    21 passed, 0 failed

### Rationale

Data health etiketleri daha önce doğrudan `ui/app.py` içinde tutuluyordu.

Bu yapı:

- UI dosyasını import etmeden mapping'i test etmeyi zorlaştırıyordu.
- Streamlit yan etkileri nedeniyle doğrudan UI testi oluşturmayı riskli hale getiriyordu.
- Label contract'ının sessizce değişmesine izin verebiliyordu.

Label mapping saf bir core helper'a taşınarak UI ve test suite tarafından ortak kullanılabilir hale getirilmiştir.

### Implementation

Yeni dosya:

    src/core/data_health_labels.py

Güncellenen dosyalar:

    ui/app.py
    src/simulation/test_reporter.py
    src/workflow/pipeline.py

Merkezi mapping şu validator anahtarlarını kapsar:

    commodity_dictionary → Ürün Sözlüğü
    supplier_capabilities → Tedarikçi Yetkinlik Matrisi
    customer_memory → Müşteri Hafızası
    hs_commodity_map → HS / GTIP Eşleştirme

Bilinmeyen validator anahtarları için okunabilir fallback label üretilir.

Örnek:

    unknown_validator_key → Unknown Validator Key

### Consequences

- UI label mapping merkezi hale geldi.
- Streamlit uygulaması import edilmeden mapping test edilebilir.
- Bilinen validator etiketleri regression test ile korunur.
- Bilinmeyen validator anahtarları için güvenli fallback bulunur.
- Test suite toplamı 20'den 21'e çıkmıştır.
