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
