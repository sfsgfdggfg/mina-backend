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

## DEC-068 — Data Health Check Registry v1

**Status:** Accepted  
**Date:** 2026-07-10

### Decision

Data health check tanımlarının merkezi bir registry üzerinden yönetilmesine karar verilmiştir.

Yeni core dosyası:

    src/core/data_health_registry.py

Registry her data health check için şu bilgileri tutar:

    key
    label
    validator

Yeni registry yapısı:

    DATA_HEALTH_CHECKS
    get_data_health_checks()
    get_data_health_check_keys()
    get_data_health_check_labels()
    run_data_health_checks()

### Rationale

Data health check listesi daha önce birden fazla dosyada hardcoded şekilde bulunuyordu:

    src/core/data_health.py
    src/core/data_health_labels.py
    src/simulation/test_reporter.py
    ui/app.py
    docs

Bu yapı yeni validator eklenirken hata riskini artırıyordu.

Merkezi registry ile data health check key, label ve validator fonksiyonu tek noktada yönetilir.

### Implementation

Yeni dosya:

    src/core/data_health_registry.py

Güncellenen dosyalar:

    src/core/data_health.py
    src/core/data_health_labels.py
    src/simulation/test_reporter.py

`build_data_health_summary()` artık validator listesini doğrudan kendi içinde tutmaz. Bunun yerine registry üzerinden `run_data_health_checks()` çağırır.

`get_data_health_check_label()` artık label sözlüğünü doğrudan kendi içinde tutmaz. Bunun yerine registry üzerinden `get_data_health_check_labels()` çağırır.

Data health summary ve label mapping testleri artık beklenen check listesini registry’den alır.

### Consequences

- Data health check listesi merkezi hale geldi.
- Yeni validator ekleme süreci daha güvenli hale geldi.
- Summary, label ve regression testleri aynı registry kaynağına bağlandı.
- Hardcoded check listeleri azaltıldı.
- Test suite sonucu korunmuştur: 21 passed, 0 failed.

## DEC-069 — Data Health Registry Integrity Test v1

**Status:** Accepted  
**Date:** 2026-07-10

### Decision

Data health registry yapısının test suite içinde ayrı bir integrity test ile doğrulanmasına karar verilmiştir.

Yeni test:

    Data health registry integrity

Test suite sonucu:

    22 passed, 0 failed

### Rationale

Data health check tanımları artık merkezi registry üzerinden yönetilmektedir:

    src/core/data_health_registry.py

Bu registry; data health summary, UI label mapping ve regression testleri için kritik kaynak haline gelmiştir.

Registry bozulursa şu alanlar etkilenebilir:

    /data-health/summary
    Data Sağlığı Dashboard
    label mapping
    data health regression testleri

Bu nedenle registry'nin kendi bütünlüğü test edilmelidir.

### Implementation

Güncellenen dosyalar:

    src/simulation/test_reporter.py
    src/workflow/pipeline.py

Yeni evaluator:

    evaluate_data_health_registry_integrity()

Test şu kontrolleri yapar:

    Registry boş değil mi?
    Her check key geçerli mi?
    Her label geçerli mi?
    Her validator callable mı?
    Duplicate key var mı?
    Duplicate label var mı?
    Validator çalıştırıldığında dict dönüyor mu?
    Validator sonucu valid anahtarı içeriyor mu?

### Consequences

- Data health registry artık test suite tarafından korunur.
- Yeni validator eklenirken registry hataları daha erken yakalanır.
- Data health summary ve label mapping altyapısı daha güvenli hale geldi.
- Test suite toplamı 21'den 22'ye çıkmıştır.

## DEC-070 — Data Health Summary Check Metadata v1

**Status:** Accepted  
**Date:** 2026-07-12

### Decision

Data health summary içindeki her validator sonucuna kullanıcı dostu görüntüleme metadata'sı eklenmesine karar verilmiştir.

Her check sonucu artık registry'de tanımlanan `label` alanını içerir.

Örnek:

    "commodity_dictionary": {
        "label": "Ürün Sözlüğü",
        "valid": true,
        "errors": [],
        "warnings": []
    }

### Rationale

Data health summary daha önce yalnızca teknik check anahtarlarını içeriyordu:

    commodity_dictionary
    supplier_capabilities
    customer_memory
    hs_commodity_map

Bu anahtarlar geliştirici için anlamlıdır ancak harici istemciler ve kullanıcı arayüzleri için yeterince açıklayıcı değildir.

Check sonucuna kullanıcı dostu label eklenmesiyle API contract kendi kendini açıklayan bir yapıya kavuşur.

### Implementation

Güncellenen dosyalar:

    src/core/data_health_registry.py
    src/simulation/test_reporter.py
    src/workflow/pipeline.py
    ui/app.py

`run_data_health_checks()` her validator sonucuna registry'deki label bilgisini ekler.

UI, check adını gösterirken öncelikle API sonucundaki `label` alanını kullanır.

API sonucunda label bulunmaması halinde merkezi helper fallback olarak korunur:

    get_data_health_check_label()

Yeni regression testi:

    Data health summary check metadata

Test şu davranışları doğrular:

    Her registry check'i summary içinde bulunur.
    Her check sonucu dictionary yapısındadır.
    Her check sonucu label metadata'sı içerir.
    Label değeri registry'deki label ile eşleşir.

Test suite sonucu:

    23 passed, 0 failed

### Consequences

- Data health summary kendi kendini açıklayan bir API contract haline geldi.
- Harici istemciler teknik check anahtarlarını çevirmek zorunda kalmaz.
- UI label bilgisini doğrudan API sonucundan okuyabilir.
- Merkezi label helper güvenli fallback olarak korunur.
- Yeni validator eklendiğinde display metadata otomatik olarak registry'den alınır.


## DEC-071 — ADR Parser and Consistency Guard v1

**Status:** Accepted  
**Date:** 2026-07-12

### Decision

ADR durumunun yalnızca AI çıkarımına bırakılmamasına ve ham email metni üzerinden deterministik safety override uygulanmasına karar verilmiştir.

Yeni davranış:

    Email açıkça ADR diyorsa:
    is_adr = true

    ADR sınıfı belirtilmişse:
    adr_class = belirtilen sınıf

    ADR belirtilmiş ancak sınıf yoksa:
    is_adr = true
    adr_class = null
    fiyat akışı durur
    clarification email hazırlanır

    Email ADR olmadığını açıkça söylüyorsa:
    is_adr = false
    adr_class = null

    Email içinde ADR ifadesi yoksa:
    AI tarafından varsayılan ADR bilgisi sıfırlanır

### Rationale

AI parser aynı veya benzer girdilerde zaman zaman ADR bilgisini yanlışlıkla varsayabiliyordu.

Bu durum şu risklere yol açıyordu:

    ADR olmayan yükün ADR olarak işaretlenmesi
    ADR sınıfı bilinmeyen yükte standart ekipman seçilmesi
    ADR sınıfı eksikken fiyat oluşturulması
    Operational consistency kontrolünün belirsiz ADR durumunu sessizce geçirmesi

ADR operasyonel olarak yüksek etkili bir bilgidir ve deterministik kontrol gerektirir.

### Implementation

Güncellenen dosyalar:

    src/ai/email_parser.py
    src/core/missing_info.py
    src/core/risk.py
    src/core/equipment.py
    src/core/operational_consistency.py
    src/ai/clarification_generator.py
    src/simulation/ai_email_test_cases.py
    src/simulation/test_reporter.py

Parser safety override şu davranışları destekler:

    ADR Class 1
    ADR sınıf 7
    ADR belirtilmiş ancak sınıf eksik
    non-ADR
    ADR değildir
    ADR kapsamında değildir
    not subject to ADR

ADR sınıfı eksikse yeni kritik missing field eklenir:

    adr class

Bu durumda ekipman kararı:

    ADR Equipment Review

Clarification email şu bilgiyi ister:

    Yükün ADR sınıfı ve varsa alt sınıfı

Operational consistency şu durumu hata olarak işaretler:

    ADR sınıfı eksik

Yeni regression testleri:

    ADR class missing
    Non-ADR negation

Test suite sonucu:

    25 passed, 0 failed

### Consequences

- ADR statüsü ham email metninden deterministik olarak belirlenir.
- AI tarafından yanlışlıkla varsayılan ADR bilgisi engellenir.
- ADR sınıfı eksikken fiyat oluşturulmaz.
- Belirsiz ADR yükünde standart ekipman seçilmez.
- Clarification email ADR sınıfını açıkça ister.
- Operational consistency ADR belirsizliğini hata olarak gösterir.

## DEC-072 — General ADR Equipment and Supplier Guard v1

**Status:** Accepted  
**Date:** 2026-07-14

### Decision

Class 1 ve 7 dışındaki ADR yüklerinde de standart ekipman ve genel taşıyıcı seçilmemesine karar verilmiştir.

Yeni davranış:

    ADR sınıfı eksik:
    ADR Equipment Review

    ADR Class 1 veya 7:
    Special ADR Equipment

    Diğer bilinen ADR sınıfları:
    ADR-Capable Equipment

ADR yüklerinde supplier selection yalnızca special_capabilities içinde adr yetkinliği bulunan tedarikçilere izin verir.

Operational consistency, seçilen tedarikçinin ADR yetkinliğini ayrıca doğrular.

### Implementation

Güncellenen alanlar:

    src/core/equipment.py
    src/core/supplier_selection.py
    src/core/operational_consistency.py
    src/core/missing_info.py
    src/simulation/ai_email_test_cases.py
    src/simulation/test_reporter.py
    data/supplier_capabilities.json

ADR Secure Logistics profiline şu ekipman desteği eklenmiştir:

    ADR-Capable Equipment

Yeni regression senaryosu:

    ADR Class 3 standard

Bu senaryoda doğrulanan davranışlar:

    is_adr = true
    adr_class = 3
    equipment = ADR-Capable Equipment
    selected supplier = ADR Secure Logistics
    non-ADR suppliers rejected
    operational consistency passed

Kimyasal ürün profilinde ADR sınıfı zaten açıkça biliniyorsa sistem müşteriden tekrar ADR statüsü istemez.

Test suite sonucu:

    26 passed, 0 failed

### Consequences

- Tüm ADR sınıflarında ADR uyumlu ekipman kararı zorunludur.
- ADR yetkinliği olmayan tedarikçiler ADR yüklerinde elenir.
- Supplier selection ve operational consistency aynı güvenlik kuralını uygular.
- Bilinen ADR statüsü için gereksiz clarification soruları azaltılır.

## DEC-073 — ADR Supplier Class Capability Guard v1

**Status:** Accepted  
**Date:** 2026-07-14

### Decision

ADR Class 1 ve Class 7 yüklerinde genel ADR yetkinliğinin tek başına yeterli olmamasına karar verilmiştir.

Yeni supplier capability kuralları:

    ADR Class 1:
    adr + class_1 zorunlu

    ADR Class 7:
    adr + class_7 zorunlu

    Diğer ADR sınıfları:
    genel adr yetkinliği yeterli

Supplier selection, gerekli sınıf yetkinliği bulunmayan supplier adayını seçim aşamasında eler.

Operational consistency, seçilen supplier için aynı sınıf yetkinliğini bağımsız olarak doğrular.

### Implementation

Güncellenen alanlar:

    src/core/supplier_selection.py
    src/core/operational_consistency.py
    src/simulation/ai_email_test_cases.py
    src/simulation/test_reporter.py
    data/supplier_capabilities.json

Regression amacıyla yeni demo supplier eklenmiştir:

    General ADR Logistics

Bu supplier:

    adr = true
    class_1 = false
    class_7 = false

Beklenen davranış:

    ADR Class 7:
    General ADR Logistics elenir

    ADR Class 3:
    General ADR Logistics seçilebilir

Bu ayrım, genel ADR yetkinliği ile yüksek riskli ADR sınıf yetkinliğinin birbirinden bağımsız ele alınmasını sağlar.

Test suite sonucu:

    26 passed, 0 failed

### Consequences

- Class 1 ve Class 7 yüklerinde sınıf bazlı supplier doğrulaması zorunludur.
- Genel ADR supplier yüksek riskli ADR sınıflarına otomatik olarak uygun sayılmaz.
- Class 1/7 dışındaki ADR sınıflarında genel ADR supplier kullanılabilir.
- Supplier selection ve operational consistency aynı sınıf yetkinliği kuralını uygular.

## DEC-074 — ADR Capability Data Validation v1

**Status:** Accepted  
**Date:** 2026-07-14

### Decision

Supplier capability datasındaki ADR bilgilerinin yalnızca runtime selection sırasında değil, veri doğrulama aşamasında da kontrol edilmesine karar verilmiştir.

Yeni validation kuralları:

    class_1 veya class_7 capability varsa:
    genel adr capability zorunlu

    Special ADR Equipment varsa:
    genel adr capability zorunlu

    ADR-Capable Equipment varsa:
    genel adr capability zorunlu

    duplicate special_capabilities:
    validation error

    bilinmeyen special_capability:
    validation error

### Implementation

Güncellenen alanlar:

    src/core/supplier_capability_validator.py
    src/simulation/test_reporter.py
    src/workflow/pipeline.py
    src/api.py

İzin verilen special capabilities merkezi olarak tanımlanmıştır.

Yeni regression testi:

    Supplier ADR capability validation

Test, geçici ve kasıtlı olarak hatalı supplier datası üretir ve şu hataların yakalandığını doğrular:

    duplicate class_7 capability
    unknown capability
    class_7 without adr
    ADR equipment without adr

Yeni evaluator hem CLI test suite hem de API test endpoint akışına bağlanmıştır.

Test suite sonucu:

    27 passed, 0 failed

### Consequences

- ADR capability veri hataları runtime öncesinde yakalanır.
- Data Health supplier validation bu kuralları otomatik olarak uygular.
- Yanlış ADR ekipman/capability kombinasyonları sessizce sisteme giremez.
- CLI ve API test akışları aynı regression kontrolünü çalıştırır.

## DEC-075 — Supplier Capability Registry v1

**Status:** Accepted  
**Date:** 2026-07-14

### Decision

Supplier capability isimlerinin validator, supplier selection ve operational consistency içinde ayrı ayrı string olarak tutulmamasına karar verilmiştir.

Capability adları merkezi registry üzerinden yönetilecektir.

Yeni merkezi dosya:

    src/core/supplier_capability_registry.py

Registry şu alanları içerir:

    adr
    class_1
    class_7
    reefer
    temperature_controlled
    cold_chain
    ltl
    partial
    parsiyel

Ayrıca yüksek riskli ADR sınıfları için merkezi mapping sağlar:

    ADR Class 1 -> class_1
    ADR Class 7 -> class_7

### Implementation

Güncellenen alanlar:

    src/core/supplier_capability_registry.py
    src/core/supplier_capability_validator.py
    src/core/supplier_selection.py
    src/core/operational_consistency.py

Validator, izin verilen capability listesini registry'den alır.

Supplier selection, genel ADR capability ve sınıf bazlı ADR capability gereksinimlerini registry üzerinden çözer.

Operational consistency aynı registry ve mapping'i kullanır.

Test suite sonucu:

    27 passed, 0 failed

### Consequences

- Capability isimleri tek merkezden yönetilir.
- Validator, selection ve consistency arasında string ayrışması riski azalır.
- Yeni capability ekleme süreci daha kontrollü hale gelir.
- ADR Class 1 ve 7 mapping'i tek yerde tutulur.

## DEC-076 — Data-Driven Supplier Capability Registry v1

**Status:** Accepted  
**Date:** 2026-07-14

### Decision

Supplier capability isimleri ve yüksek riskli ADR sınıf mapping'lerinin kod içinde sabit tutulmamasına karar verilmiştir.

Yeni veri dosyası:

    data/supplier_capability_registry.json

Bu dosya şu alanları yönetir:

    allowed_special_capabilities
    adr_class_capability_map

Örnek ADR class mapping:

    ADR Class 1 -> class_1
    ADR Class 7 -> class_7

Runtime registry bu JSON dosyasını yükler.

### Implementation

Güncellenen alanlar:

    data/supplier_capability_registry.json
    src/core/supplier_capability_registry.py
    src/core/supplier_capability_registry_validator.py
    src/core/data_health_registry.py
    src/simulation/test_reporter.py
    src/workflow/pipeline.py
    src/api.py

Yeni validator şu hataları kontrol eder:

    registry root formatı
    allowed capability listesi
    duplicate capability
    adr capability varlığı
    ADR class mapping formatı
    mapping target capability'nin allowed listede bulunması

Yeni Data Health check:

    supplier_capability_registry
    Tedarikçi Yetkinlik Registry

Yeni regression testi:

    Supplier capability registry validation

Test suite sonucu:

    28 passed, 0 failed

### Consequences

- Capability isimleri veri tabanlı hale gelir.
- ADR class mapping kod değişikliği olmadan registry verisi üzerinden güncellenebilir.
- Hatalı mapping ve duplicate capability Data Health aşamasında yakalanır.
- CLI ve API test akışları registry validation regression testini çalıştırır.

## DEC-077 — Supplier Capability Registry Runtime Integrity Guard v1

**Status:** Accepted
**Date:** 2026-07-14

### Decision

Supplier capability registry runtime yükleme hatalarının ham FileNotFoundError, JSONDecodeError veya ValueError olarak zincirleme yayılmamasına karar verilmiştir.

Registry yükleme hataları tek tip kontrollü exception üzerinden yönetilecektir:

    SupplierCapabilityRegistryError

Runtime loader şu durumları açıkça ayırır:

    registry file missing
    invalid JSON
    registry root is not an object

Registry loader ayrıca test edilebilir hale getirilmiştir:

    load_supplier_capability_registry(path)

Bu sayede gerçek production registry dosyasına dokunmadan geçici test dosyalarıyla runtime integrity regression testi yapılabilir.

### Implementation

Güncellenen alanlar:

    src/core/supplier_capability_registry.py
    src/simulation/test_reporter.py
    src/workflow/pipeline.py
    src/api.py

Yeni metadata fonksiyonu:

    get_supplier_capability_registry_metadata()

Metadata şu bilgileri döndürür:

    source
    loaded
    allowed_capability_count
    adr_class_mapping_count

Yeni regression testi:

    Supplier capability registry runtime integrity

Test edilen runtime failure senaryoları:

    missing file
    invalid JSON
    non-object root

Bu senaryoların tamamında:

    SupplierCapabilityRegistryError

beklenir.

Yeni evaluator hem CLI hem API test akışına bağlanmıştır.

Test suite sonucu:

    29 passed, 0 failed

### Consequences

- Registry runtime yükleme hataları kontrollü ve açıklayıcı hale gelir.
- Import zincirindeki hata nedeni daha kolay teşhis edilir.
- Gerçek registry dosyasına dokunmadan failure senaryoları test edilebilir.
- Registry yükleme durumu metadata üzerinden gözlemlenebilir.

## DEC-078 — Quote Readiness Decision Engine v1

**Status:** Accepted  
**Date:** 2026-07-15

### Decision

Fiyat/teklif hazırlığı kararının farklı workflow koşullarından dolaylı olarak türetilmemesine karar verilmiştir.

Yeni merkezi karar motoru:

    src/core/quote_readiness.py

Quote readiness karar önceliği:

    1. RED risk -> management_review
    2. Kritik eksik bilgi -> clarification
    3. Kalan operational consistency error -> blocked
    4. Yellow risk -> quote_with_review
    5. Temiz akış -> quote_ready

### Implementation

Yeni model:

    QuoteReadinessDecision

Alanlar:

    result_type
    can_generate_quote
    requires_human_review
    reasons
    source

Yeni karar motoru:

    decide_quote_readiness(...)

Pipeline artık risk, missing info ve operational consistency sonuçlarını merkezi quote readiness motorunda birleştirir.

Yeni result type:

    blocked

Blocked durumda:

    teklif oluşturulmaz
    insan kontrolü gerekir
    operational consistency hataları neden olarak taşınır

Action Recommendation sistemi blocked sonucunu destekler.

Pipeline çıktısına yeni alan eklenmiştir:

    quote_readiness

Test reporter şu expectation alanını destekler:

    quote_readiness_result_type

Regression testleri şu akışları doğrular:

    management_review
    clarification
    quote_with_review

ADR class missing senaryosu, eksik bilgi kaynaklı consistency error bulunduğunda blocked yerine clarification önceliğini doğrular.

Test suite sonucu:

    29 passed, 0 failed

### Consequences

- Quote readiness kararı tek merkezden yönetilir.
- Workflow karar önceliği açık ve deterministik hale gelir.
- Operational consistency hataları sessizce göz ardı edilmez.
- Eksik bilgi kaynaklı consistency hataları gereksiz blocked sonucuna dönüşmez.
- Yeni readiness durumları ileride merkezi motora eklenebilir.

## DEC-079 — Supplier RFQ Response Integrity and Stable Workflow Contract

**Status:** Accepted
**Date:** 2026-08-05

### Decision

Supplier RFQ cevaplarının fiyat seçiminde kullanılmadan önce oluşturulan RFQ taslaklarıyla kimlik ve bağlam bütünlüğü açısından doğrulanmasına karar verilmiştir.

Her supplier cevabı en az şu alanlarla ilgili RFQ taslağına bağlanmalıdır:

    rfq_id
    supplier_name
    rfq_priority

Aşağıdaki cevaplar geçersiz kabul edilmelidir:

    unknown_rfq_id
    supplier_name_mismatch
    priority_mismatch

Ham supplier cevapları denetim amacıyla korunmalı; ancak yalnızca doğrulanmış cevaplar lifecycle synchronization, supplier quote selection ve müşteri teklifi aşamalarında kullanılmalıdır.

Quoted cevaplarda pozitif maliyet zorunludur. Quoted olmayan cevaplarda maliyet bulunmamalıdır.

Geçerli fiyat cevabı bulunmadığında sistem fallback fiyat üretmemeli ve kontrollü sonuç döndürmelidir:

    supplier_response_required

Workflow ve API kontratında şu alanlar ayrıştırılmıştır:

    supplier_rfq_responses
    valid_supplier_rfq_responses
    supplier_rfq_response_validation

### Consequences

- Başka bir RFQ’ye veya tedarikçiye ait fiyat yanlışlıkla kullanılamaz.
- Geçersiz cevaplar sessizce kaybolmaz; rejection reason ile raporlanır.
- Supplier cevabı yokken yapay müşteri teklifi oluşturulmaz.
- API ve workflow aynı doğrulanmış veri kaynağını kullanır.
- RFQ lifecycle yalnızca geçerli cevaplarla `responded` durumuna geçer.

---

## DEC-080 — Multi-Criteria Supplier Quote Comparison and Traceable Selection

**Status:** Accepted
**Date:** 2026-08-05

### Decision

Supplier teklif seçiminin yalnızca RFQ önceliğine veya en düşük fiyata göre yapılmamasına karar verilmiştir.

Her kullanılabilir supplier cevabı için merkezi karşılaştırma kaydı oluşturulur:

    SupplierQuoteComparison

Karşılaştırma en az şu verileri taşır:

    rfq_id
    supplier_name
    priority
    cost
    currency
    transit_time
    supplier_score
    commercial_score
    operational_score
    actual_price_score
    transit_score
    total_score

Mevcut veri seti için seçim skoru:

    supplier_score      %70
    actual_price_score  %20
    transit_score       %10

Aynı para birimindeki en düşük fiyat `1.0` gerçek fiyat skoru alır. Diğer teklifler:

    minimum_cost / offered_cost

oranıyla puanlanır.

Transit süresi sayısal olarak okunabiliyorsa en kısa başlangıç süresi `1.0` puan alır. Transit bilgisi kullanılamıyorsa nötr `0.5` skoru uygulanır.

Seçim sırası:

    1. En yüksek total_score
    2. Eşitlikte daha düşük RFQ priority değeri
    3. Hâlâ eşitse daha düşük cost

Seçim kararı ayrıca açıklanabilir ve denetlenebilir olmalıdır:

    SupplierQuoteSelectionDecision

Karar; seçilen RFQ kimliğini, skor ve fiyat farklarını, seçim nedenini ve elenen alternatifleri taşımalıdır.

### Consequences

- En ucuz teklif operasyonel açıdan zayıfsa otomatik seçilmez.
- Seçimin neden yapıldığı kullanıcıya ve denetim katmanına açıklanabilir.
- Seçilen supplier cevabı `rfq_id` üzerinden özgün cevaba bağlanır.
- Alternatif tekliflerin fiyat ve skor farkları kaybolmaz.
- İleride yeni scorecard alanları eklendiğinde karşılaştırma modeli genişletilebilir.

---

## DEC-081 — Supplier RFQ Repository and Lifecycle Persistence Boundary

**Status:** Accepted
**Date:** 2026-08-05

### Decision

Supplier RFQ taslakları ve cevaplarının doğrudan workflow belleğine bağlı kalmaması için repository sınırı oluşturulmasına karar verilmiştir.

Merkezi sözleşme:

    SupplierRFQRepository

İlk uygulama:

    InMemorySupplierRFQRepository

Repository şu işlemleri destekler:

    save_drafts
    save_responses
    get_draft
    list_drafts
    list_responses

`process_shipment` isteğe bağlı repository bağımlılığı kabul eder. Repository verilmezse her workflow çalışması için bellek içi repository kullanılır.

Workflow şu kayıt sırasını uygular:

    1. RFQ taslaklarını oluştur ve kaydet
    2. Supplier cevaplarını al ve kaydet
    3. Cevapları doğrula
    4. RFQ lifecycle durumlarını senkronize et
    5. Güncel taslakları tekrar repository’ye kaydet

Aynı RFQ cevabının birebir tekrar kaydedilmesi engellenmelidir. Bununla birlikte daha sonra gelen ve fiyat, durum, not veya `received_at` gibi alanları değişmiş yeni cevap ayrı kayıt olarak korunmalıdır.

### Consequences

- Workflow gelecekte SQLite veya başka kalıcı storage ile değiştirilebilir.
- Pipeline kodu storage teknolojisine doğrudan bağlanmaz.
- RFQ taslağının son lifecycle durumu repository’den okunabilir.
- Birebir duplicate cevaplar kayıt sayısını şişirmez.
- Gerçek revize supplier teklifleri geçmiş kaydı olarak korunur.

---

## DEC-082 — Quote Approval Snapshot and Human Approval Requirement

**Status:** Accepted
**Date:** 2026-08-05

### Decision

Müşteri teklifinin açık insan onayı olmadan gönderilebilir kabul edilmemesine karar verilmiştir.

Her başarılı quote workflow’u şu durumda bir onay kaydı üretir:

    approval_status = pending

Onay modeli:

    QuoteApproval

Durumlar:

    pending
    approved
    rejected
    invalidated

Onay kaydı, karar anındaki teklifin değişmez snapshot’ını taşır:

    supplier_name
    supplier_cost
    final_price
    currency
    transit_time
    quote_subject
    quote_body

Approved durumda şu alanlar zorunludur:

    approved_by
    approved_at

Rejected durumda şu alan zorunludur:

    rejection_reason

Teklif fiyatı, supplier, transit süresi, konu veya gövde değişirse önceki onay güncel teklif için geçerli sayılmamalıdır.

Teklif üretilemeyen workflow branch’lerinde:

    quote_approval = None

olmalıdır.

### Consequences

- Sistem yeni teklifleri otomatik onaylamaz.
- Onayın tam olarak hangi teklif için verildiği kanıtlanabilir.
- Onaydan sonra yapılan içerik veya fiyat değişikliği eski onayı geçersiz kılar.
- Rejected ve invalidated kayıtlar gönderim yetkisi vermez.
- Workflow ve API aynı approval modelini döndürür.

---

## DEC-083 — Central Quote Send Safety and Non-Sending Preparation Service

**Status:** Accepted
**Date:** 2026-08-05

### Decision

Teklif gönderilebilirliği için merkezi bir güvenlik motoru kullanılmasına karar verilmiştir:

    evaluate_quote_send_safety(...)

Gönderim yalnızca şu iki koşul birlikte sağlandığında güvenli kabul edilir:

    approval_status = approved
    approval snapshot güncel teklif ile eşleşiyor

Kontrollü block reason değerleri:

    approval_missing
    approval_pending
    approval_rejected
    approval_invalidated
    quote_snapshot_mismatch

Başarılı quote workflow’u varsayılan olarak pending onay ürettiğinden ilk gönderim güvenliği sonucu:

    can_send = false
    block_reason = approval_pending

Gerçek e-posta sağlayıcısını çalıştırmayan hazırlık servisi oluşturulmuştur:

    prepare_quote_for_sending(...)

Servis yalnızca şu durumları döndürür:

    blocked
    send_ready

Bu aşamada servis hiçbir koşulda gerçek gönderim yapmaz:

    sent = false

API endpoint’i:

    POST /quotes/prepare-send

Endpoint geçerli onay ve güncel snapshot varsa `send_ready`, diğer durumlarda kontrollü `blocked` sonucu döndürür. Boş recipient email HTTP 422 ile reddedilir.

### Consequences

- Onaysız teklif gönderim katmanına geçemez.
- Onaydan sonra değişmiş teklif gönderilemez.
- Hazırlık ve gerçek teslimat sorumlulukları ayrılmıştır.
- Mevcut endpoint gerçek müşteriye e-posta çıkarmaz.
- Gerçek email adapter eklenmeden önce güvenlik kontratı tamamlanmıştır.
- TASK-126 sonunda test suite sonucu `56 passed, 0 failed` olmuştur.

## DEC-084 — Trusted Quote Approval Repository and API Lifecycle

**Status:** Accepted
**Date:** 2026-08-06

### Decision

Quote approval kayıtlarının istemci tarafından taşınan geçici nesnelere bağlı olmamasına karar verilmiştir.

Merkezi repository sözleşmesi:

    QuoteApprovalRepository

İlk uygulama:

    InMemoryQuoteApprovalRepository

Repository şu işlemleri destekler:

    save
    save_many
    get
    list_all

Aynı `approval_id` ile kaydedilen onay mevcut kaydı günceller.

Başarılı quote workflow’u oluşturduğu pending onayı repository’ye kaydeder. Teklif üretilemeyen early-stop branch’leri onay kaydetmez.

Onay yaşam döngüsü merkezi servis üzerinden yönetilir:

    approve_quote(...)
    reject_quote(...)
    invalidate_quote_approval(...)

Geçerli durum geçişleri:

    pending -> approved
    pending -> rejected
    pending -> invalidated
    approved -> invalidated

Terminal durumlar:

    rejected
    invalidated

Approved kayıt tekrar onaylanamaz veya reddedilemez.

API uygulama ömründe tek bir approval repository kullanır. `/process-email` ile oluşturulan pending kayıtlar aynı API süreci içinde onay endpoint’lerinden erişilebilir.

Onay API’leri:

    GET  /quote-approvals
    GET  /quote-approvals/{approval_id}
    POST /quote-approvals/{approval_id}/approve
    POST /quote-approvals/{approval_id}/reject
    POST /quote-approvals/{approval_id}/invalidate

HTTP hata kontratı:

    unknown approval_id -> 404
    invalid lifecycle transition -> 409
    empty approved_by or rejection_reason -> 422

`POST /quotes/prepare-send` artık istemciden tam `QuoteApproval` nesnesi kabul etmez.

Yeni kontrat:

    approval_id
    recipient_email
    supplier_quote
    customer_quote
    quote_draft

Gönderim hazırlığı, approval kaydını sunucu tarafındaki repository’den `approval_id` ile yükler.

### Consequences

- İstemci sahte bir approved nesnesi oluşturarak gönderim yetkisi elde edemez.
- Approval identity ve lifecycle sunucu tarafında kontrol edilir.
- Onaylama, reddetme ve geçersiz kılma işlemleri merkezi geçiş kurallarına bağlıdır.
- Onay geçmişi aynı API süreci içinde listelenebilir ve okunabilir.
- Uygulama yeniden başlatıldığında bellek içi kayıtlar silinir; kalıcı database henüz yoktur.
- Gerçek authentication ve role-based authorization henüz uygulanmamıştır.
- Grup 9 sonunda test suite sonucu `60 passed, 0 failed` olmuştur.

## DEC-085 — Quote Case as the Persistent Working Record for Quote Lifecycle

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Teklif workflow sonucunun yalnızca geçici API response olarak kalmamasına karar verilmiştir.

Başarılı teklif çalışması tek bir çalışma kaydı altında temsil edilmelidir:

    QuoteCase

Quote Case ilk sürümde şu bilgileri taşır:

    case_id
    shipment
    supplier_quote_selection_decision
    supplier_quote
    customer_quote
    quote_draft
    quote_approval
    quote_send_safety
    created_at
    updated_at
    source

Quote Case alanlarının önemli bir bölümü optional tutulmuştur.

Amaç, Quote Case'in yalnızca tamamlanmış teklif snapshot'ı değil, ileride yaşam döngüsü boyunca güncellenebilen bir iş kaydı olabilmesidir.

Quote Case, mevcut MVP kapsamında teklif çalışma dosyasıdır.

Henüz:

    booking kaydı
    taşıma operasyon dosyası
    shipment tracking kaydı
    POD kaydı
    fatura kaydı

olarak değerlendirilmemelidir.

Ancak uzun vadede daha genel bir operation/shipment case yapısının temelini oluşturabilir.

### Consequences

- Aynı teklif çalışmasına ait shipment, supplier seçimi, fiyat, draft, approval ve send safety verileri tek kimlik altında tutulur.
- Teklif bileşenleri birbirinden kopuk geçici nesneler olmaktan çıkar.
- Gelecekte revizyon, booking ve operasyon lifecycle kayıtları aynı case yaklaşımı üzerinden genişletilebilir.
- `case_id` bir teklif çalışmasının stabil kimliği haline gelir.

---

## DEC-086 — Quote Case Repository and Workflow Persistence Boundary

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Quote Case kayıtlarının doğrudan pipeline belleğine bağlı kalmaması için repository sınırı oluşturulmasına karar verilmiştir.

Merkezi sözleşme:

    QuoteCaseRepository

İlk uygulama:

    InMemoryQuoteCaseRepository

Repository şu işlemleri destekler:

    save
    save_many
    get
    list_all

Aynı `case_id` ile yapılan kayıt mevcut case'i günceller.

`process_shipment` optional olarak:

    quote_case_repository

bağımlılığı kabul eder.

Repository verilmezse workflow çağrısı için geçici:

    InMemoryQuoteCaseRepository

oluşturulur.

Başarılı quote workflow'u:

    QuoteCase oluşturur
    repository'ye kaydeder
    workflow sonucunda quote_case alanını döndürür

Teklif üretmeyen early-stop branch'leri:

    quote_case = None

döndürmeli ve repository'ye case yazmamalıdır.

### Consequences

- Pipeline storage teknolojisine doğrudan bağlanmaz.
- Quote Case ileride database repository ile değiştirilebilir.
- Aynı `case_id` üzerinden çalışma kaydı tekrar yüklenebilir.
- Early-stop akışları yanlışlıkla tamamlanmış teklif dosyası oluşturmaz.

---

## DEC-087 — Quote Case API Retrieval and Application-Lifetime Repository

**Status:** Accepted
**Date:** 2026-08-11

### Decision

API süreci içinde oluşturulan Quote Case kayıtlarının sonraki API çağrılarından erişilebilir olması için uygulama ömründe ortak Quote Case repository kullanılmasına karar verilmiştir.

API repository:

    quote_case_repository = InMemoryQuoteCaseRepository()

`POST /process-email` başarılı quote workflow'unda aynı repository'yi pipeline'a geçirir.

API response serialization artık:

    quote_case

alanını içerir.

Quote Case erişim endpoint'leri:

    GET /quote-cases
    GET /quote-cases/{case_id}

Bilinmeyen case:

    HTTP 404

ile reddedilir.

Quote Case API contract testi AI parser davranışına bağlı olmamalıdır.

Regression test sırasında parser deterministik Shipment ile izole edilmelidir.

### Consequences

- `/process-email` ile oluşturulan case aynı API süreci içinde yeniden okunabilir.
- Quote Case listelenebilir ve `case_id` ile geri çağrılabilir.
- API contract testi dış AI değişkenliğinden bağımsız hale gelir.
- InMemory repository uygulama restart olduğunda kayıtları kaybeder; bu gerçek kalıcı storage değildir.
- Grup 10 sonunda test suite sonucu `64 passed, 0 failed` olmuştur.

---

## DEC-088 — Resolvable Commodity Clarification Contract

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Commodity profile tarafından üretilen kritik clarification sorularının cevabını
saklayacak ve missing-info tarafından tekrar değerlendirecek genel bir domain
kontratı oluşturulmuştur.

Canonical requirement tanımı:

    operational_profile.clarification_requirements

Her requirement:

    key
    value_type
    question
    critical

alanlarını taşır. Shipment cevapları:

    commodity_attributes

map'i içinde saklar. Key'in bulunmaması bilgi verilmediğini, key ile birlikte
`false` bulunması ise müşterinin açık olumsuz cevabını ifade eder.

Yeni domain servisi structured cevapları type ve commodity kapsamı açısından
doğrular, Shipment kopyasına atomik uygular ve missing-info engine'in aynı
canonical requirement tanımlarıyla quote readiness'i yeniden hesaplamasına izin
verir.

AI structured extraction modeli de aynı canonical key ve type bilgisini kullanır.
Clarification draft metni ayrı bir translation tablosundan değil requirement
`question` alanından üretilir.

### Consequences

* Commodity clarification soruları kalıcı dead-end oluşturmaz.
* Explicit false ile eksik bilgi birbirinden ayrılır.
* Unknown veya başka commodity'ye ait key kontrollü olarak reddedilir.
* Eski `missing_info_fields` ve `critical_missing_info_fields` API görünümü canonical tanımlardan türetilir.
* Reply ingestion, database persistence ve UI değişikliği bu kararın kapsamı dışındadır.

---

## DEC-089 — Regulatory Document Gate and Separate Exception Review

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Kritik clarification cevapları ile teklif öncesi düzenleyici uygunluk kararının
ayrı domain sorumlulukları olarak modellenmesine karar verilmiştir.

Regulatory blocking semantics için tek canonical kaynak requirement metadata'sıdır:

    operational_profile.clarification_requirements[].compliance_policy

Metadata şu alanları taşır:

    policy_type = regulatory_document
    document_label
    required_before_quote
    customer_promise_requires_human_review

Bu karar capability ile gerçek hukuki sınıflandırmayı birbirinden ayırır.
Requirement adında `document`, `compliance`, `ruhsat`, `MSDS` veya benzeri bir
ifadenin bulunması; alanın kritik clarification olması ya da descriptive metinde
mevzuat riskiyle ilişkilendirilmesi tek başına regulatory blocking için yeterli
değildir. Blokaj yalnızca canonical requirement verisinde doğrulanmış
`compliance_policy` metadata'sı açıkça bulunduğunda etkinleşir.

Şu an aşağıdaki production requirement'lar için precise legal applicability
doğrulanmış değildir ve bu nedenle regulatory policy aktive edilmemiştir:

    msds/sds document
    medical compliance document
    pharma compliance document

Bu requirement'lar mevcut commodity kuralları uyarınca clarification, risk veya
genel human-review davranışını sürdürebilir. Explicit false cevap, doğrulanmış
policy metadata'sı olmadan hukuki yasak veya regulatory block sayılmaz.

Yeni focused domain boundary:

    src/core/regulatory_compliance.py

Shipment, müşteri taahhüdüne bağlı istisna incelemesini ayrı bir map içinde taşır:

    regulatory_exception_reviews

Review durumları:

    pending
    approved
    rejected

Bu lifecycle commercial quote snapshot'ını onaylayan `QuoteApproval` içine
yerleştirilmemiştir. Regulatory exception, teklif oluşturulmadan önce çözülmesi
gereken farklı bir yetki ve sorumluluktur.

Quote readiness'e iki açık sonuç eklenmiştir:

    regulatory_blocked
    regulatory_review

Pending durum onay sayılmaz. Sadece `decided_by` ve `decided_at` bilgileriyle
kaydedilmiş explicit approved review normal kontrollere devam izni verir. Rejected
veya review bulunmayan explicit false durumu otomatik teklifi engeller.

### Consequences

* Missing, known-unavailable ve promised-later durumları birbirine karışmaz.
* Müşteri taahhüdü MINAI tarafından otonom istisna onayına çevrilmez.
* Regulatory policy document-name-specific koşullar yerine data metadata'sından okunur.
* Başarılı quote case, kullanılan regulatory compliance assessment'ı audit amacıyla taşır.
* Natural-language reply ingestion, review persistence ve review API lifecycle bu değişikliğin kapsamı dışındadır.
* Production commodity requirements için henüz regulatory blocking aktive edilmemiştir.
* Belge setlerinin ülke/ürün bazlı hukuki uygulanabilirliği ayrı regulatory knowledge katmanı gerektirir.

---

## DEC-090 — Explicit Human-Controlled Supplier RFQ Lifecycle

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Supplier RFQ generation ile outbound send aynı işlem olarak ele alınmayacaktır.
Lifecycle geçişleri merkezi supplier RFQ service tarafından uygulanacaktır:

    draft
    -> approved (approved_by, approved_at)
    -> awaiting_response (sent_at)
    -> responded (responded_at)

`/process-email` shipment readiness ve supplier selection sonrasında RFQ draft'ları
oluşturup `supplier_rfq_approval_required` sonucunda durur. Bu çağrı supplier
response simulation, supplier comparison, customer pricing veya commercial quote
approval üretmez.

In-memory Supplier RFQ repository application lifetime boyunca draft, response ve
shipment workflow context'ini tutar. API ayrı approve, send, attach/simulate
response, retrieve ve resume-quote operasyonları sunar. Send operasyonu şu an
gerçek email teslimatı yapmaz; yalnızca gelecekteki Outlook/SMTP adapter'ından
önceki outbound lifecycle boundary'sini temsil eder.

Supplier response yalnızca `sent` / `awaiting_response` RFQ'ya bağlanabilir.
Response link doğrulaması sonrası RFQ `responded` olur. Supplier comparison,
yalnızca `responded` RFQ'ların usable response'larını kullanır. En az bir usable
supplier price oluştuğunda workflow customer pricing'e devam eder ve bundan sonra
ayrı, pending commercial `QuoteApproval` oluşturur.
Oluşan Quote Case, audit traceability için kaynak Supplier RFQ workflow kimliğini
`supplier_rfq_workflow_id` alanında taşır.

### Consequences

* RFQ generation is not RFQ sending.
* A supplier response cannot exist for an RFQ that has not been sent.
* RFQ approval ile customer quote commercial approval birbirinden ayrıdır.
* Simulated response otomatik email-processing yan etkisi olmaktan çıkarılmıştır.
* Unknown identity, invalid transition, unsent response ve duplicate operation'lar fail-closed davranır.
* Gerçek email delivery, inbox parsing, database, authentication ve asynchronous jobs bu kararın kapsamı dışındadır.

---

## DEC-091 — Provider-Neutral Supplier Response Ingestion Boundary

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Future mailbox adapter'larının çağıracağı provider-neutral supplier reply
ingestion boundary oluşturulmuştur. Inbound model sender address/name, subject,
body, received timestamp, external message identity, optional explicit RFQ
reference, source ve provider label taşır; provider SDK nesnesi taşımaz.

Generated RFQ subject/body içine stable reference eklenir:

    MINAI-RFQ:<rfq_id>

Correlation merkezi ve deterministiktir. Explicit reference subject token'dan,
subject token supplier-only eşleşmeden önce değerlendirilir. Supplier-only
eşleşme yalnızca sender address'in tek bir `awaiting_response` RFQ'ya bağlanması
halinde kabul edilir. Unresolved, ambiguous, invalid supplier ve non-awaiting
durumları attachment üretmeden açık ingestion result olarak döner.

Structured extraction contract commercial alanların provided, not-provided veya
uncertain durumunu ayırır. Parser RFQ kimliği seçmez ve lifecycle mutation yapmaz.
Parser çalıştırılmadan önce correlation/lifecycle boundary kontrol edilir; parser
çıktısı daha sonra Pydantic response validation ve merkezi
`attach_supplier_rfq_response` service'inden geçer.

Quoted response için cost ve currency explicit zorunludur. Supplier reply
currency'si için EUR default'u kaldırılmıştır. Non-quote response cost/currency
taşıyamaz. External message identity başarılı attachment sonrasında in-memory
repository'de deduplication amacıyla kaydedilir. Aynı message veya cevap mevcut
response'u overwrite etmez.

API yalnızca provider-neutral bir manual/raw ingestion endpoint'i sunar:

    POST /supplier-responses/ingest

Endpoint business logic taşımaz; application service'e delege eder. Structured
fixture verilmez ve parser bağlı değilse `parsing_required` sonucu döner. Future
AI/Graph adapter'ları aynı application boundary'yi kullanacaktır.

### Consequences

* Inbound supplier content is untrusted commercial input, not operational authority.
* RFQ correlation must fail closed when identity is unresolved or ambiguous.
* AI extraction deterministic identity ve lifecycle validation'ı bypass edemez.
* Successful ingestion customer quote progression'ı otomatik başlatmaz.
* Outlook/Graph, mailbox polling, webhook, database ve authentication bu kararın kapsamı dışındadır.

---

## DEC-092 — Provider-Neutral Mail Adapter Boundary

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Inbound ve outbound email işlemleri için provider-neutral application boundary
oluşturulmuştur. Canonical inbound envelope yalnızca MINAI'nin bugün kullandığı
message identity, provider/mailbox identity, sender/recipient, subject, text body,
received timestamp ve reply/RFQ reference metadata'sını taşır. Supplier reply
ingestion ayrı bir inbound model tutmak yerine aynı canonical envelope'i tüketir.
Customer `/process-email` akışı da body text'i değiştirmeden bu envelope üzerinden
mevcut parser ve shipment workflow'una aktarır.

Outbound contract; stable operation identity, recipients, subject, text body,
message purpose ve optional correlation metadata taşır. Purpose değerleri customer
clarification, supplier RFQ ve customer quote ile sınırlıdır. Provider interface
yalnızca canonical request'i gönderir ve `sent`, `failed`,
`rejected_before_provider` veya `provider_unavailable` sonucu döndürür. Raw
provider exception'ları application sonucuna sızdırılmaz.

Supplier RFQ mail application service'i approval ve lifecycle state'ini provider
çağrısından önce kontrol eder. Yalnızca provider'ın confirmed `sent` sonucu
sonrasında merkezi RFQ lifecycle transition çağrılır. Failure/unavailable sonucu
RFQ'yu `approved` ve retryable bırakır. Stable `supplier-rfq:<rfq_id>` operation
identity future provider idempotency'si için kullanılır; already-sent RFQ provider'a
yeniden verilmez.

DEC-090 içindeki gerçek teslimat olmadan send boundary'sinin `awaiting_response`
durumuna geçebileceği yönündeki geçici yaklaşım bu kararla supersede edilmiştir.
Provider yapılandırılmamış API send çağrısı teslimat varsaymaz; controlled
`provider_unavailable` sonucu döner ve lifecycle'ı ilerletmez.

Customer quote preparation mevcut QuoteApproval ve send-safety motorunu authority
olarak kullanmaya devam eder. Olumsuz karar provider çağrısından önce
`rejected_before_provider` olur. Olumlu karar canonical outbound request üretir ve
future provider adapter üzerinden gönderilebilir. Clarification draft için ortak
request builder vardır; bu builder herhangi bir send side effect'i üretmez.

### Consequences

* Mail providers transport messages; they do not authorize business actions.
* Lifecycle advancement after outbound email requires confirmed provider send success.
* Provider SDK objects core/domain ve workflow contract'larına girmez.
* RFQ failure retryable kalır; distributed retry queue veya delivery persistence yoktur.
* Customer quote delivery sonucu henüz persistent quote lifecycle state'i oluşturmaz.
* Outlook, Graph, SMTP, IMAP, OAuth, polling, webhook, attachment, HTML ve threading kapsam dışıdır.

---

## DEC-093 — Human Extraction Confirmation as Operational Authority Boundary

**Status:** Accepted
**Date:** 2026-08-11

### Decision

Customer email AI parser çıktısının doğrudan operational `Shipment` olarak
pipeline'a girmemesi kararlaştırılmıştır.

**AI-extracted shipment facts are proposals until explicitly confirmed by a
human operator. Only a confirmed shipment snapshot may acquire operational
authority.**

Yeni domain contract'ları:

    ShipmentProposalSnapshot
    ShipmentExtractionProposal
    ExtractionProposalRepository

İlk implementation application-lifetime in-memory repository kullanır. Proposal;
canonical `InboundMailEnvelope`, ilk normalize AI snapshot'ı, confirmation state,
operator corrections, changed fields, confirmed snapshot ve confirmation
metadata'sını birlikte korur.

Lifecycle:

    POST /process-email
    -> extraction_confirmation_required

    GET /extraction-proposals/{proposal_id}
    -> inspect original proposal

    POST /extraction-proposals/{proposal_id}/confirm
    -> confirm unchanged or atomically correct and confirm

    POST /extraction-proposals/{proposal_id}/resume
    -> existing deterministic workflow using confirmed Shipment only

Unconfirmed proposal customer-memory enrichment, missing-info, regulatory,
equipment, risk, supplier selection, readiness, RFQ generation veya pricing
çalıştıramaz. `process_shipment` de proposal snapshot'ını doğrudan kabul etmez.

AI extraction schema'daki safety-sensitive boolean alanları optional yapılmıştır.
`null` unknown, `false` explicit negative anlamındadır. Confirm operation;
`is_adr`, `is_temperature_controlled` ve `is_high_value` alanlarının explicit
çözülmesini zorunlu tutar ve ancak bundan sonra boolean kullanan operational
Shipment oluşturur.

Duplicate confirmation mevcut confirmed snapshot'ı overwrite etmez. Unknown
proposal, invalid correction, unresolved safety fact ve duplicate resume
fail-closed davranır. İlk AI proposal correction sonrasında değişmeden kalır.

DEC-092 içindeki customer mail'in doğrudan mevcut shipment workflow'una devam
etmesi yaklaşımı bu authority checkpoint bakımından supersede edilmiştir;
provider-neutral mail contract'ı değişmemiştir.

### Consequences

* Customer memory yalnızca confirmed snapshot sonrasında çalışır.
* Existing clarification, regulatory, supplier RFQ, response ingestion ve mail
  delivery safety sınırları korunur.
* Operator identity bu aşamada claimed metadata'dır; P0.2 authentication değildir.
* Repository restart-safe değildir; durable pilot evidence P0.3 kapsamındadır.
* Sender/customer identity trust modeli P0.4 kapsamındadır.
* Full Streamlit confirmation UI, analytics ve outbound provider kapsam dışıdır.


---

## DEC-094 — Trusted Sender Boundary for Customer Memory

**Status:** Accepted
**Date:** 2026-08-12

### Decision

Customer-memory enrichment will no longer infer customer identity from arbitrary
message text. The confirmed shipment customer name establishes only a candidate
profile.

Automatic enrichment requires trusted identity evidence from the canonical
inbound mail envelope: an exact configured sender address or configured sender
domain on the customer profile.

Current customer profiles have no trusted sender mapping by default; therefore
memory enrichment remains safely inactive for them until trusted mappings are
configured.

`/process-email` now preserves optional sender, subject, and external message
metadata so that the extraction proposal retains identity evidence for later
confirmation and resume.

### Consequences

* Forwarded/quoted mentions cannot silently activate another customer's memory.
* Missing or untrusted sender identity cannot inject customer defaults.
* Trusted sender configuration remains explicit customer reference data.
* Human extraction confirmation remains necessary but is not itself sender
  authentication.
* Full authenticated operator/customer identity management remains outside this
  decision and is handled separately under the pilot security controls.


---

## DEC-095 — SQLite Durable State and Append-Only Pilot Evidence

**Status:** Accepted
**Date:** 2026-08-12

### Decision

The pre-MVP shadow-pilot runtime will replace API-global in-memory repositories with SQLite-backed adapters that preserve the existing repository contracts.

A shared `SQLitePilotStore` persists current validated snapshots for extraction proposals, supplier RFQ drafts/workflows/responses, supplier inbound-message deduplication keys, quote approvals, and quote cases.

The same store maintains an append-only `pilot_events` audit trail. Each process startup has a `run_id`; every repository write records the validated snapshot, entity identity, event type, run ID, and timestamp.

The default pilot database path is `data/pilot/minai_pilot.sqlite3`, overridable with `MINAI_PILOT_DB_PATH`. The pilot data directory is excluded from Git.

This is intentionally a small single-process pilot persistence layer, not the production database architecture.

### Consequences

* Restart no longer erases the main quote/RFQ/extraction lifecycle state.
* Supplier response and inbound-message deduplication survive restart.
* Historical save snapshots can be reconstructed from append-only pilot events.
* Existing workflow services continue to depend on repository protocols rather than SQLite directly.
* No public evidence API is added while API authentication remains a P0 item.
* SQLite persistence does not provide privacy approval, operator authentication, encryption policy, retention policy, multi-tenant isolation, migrations, or production concurrency guarantees.
* Real customer/company data remains prohibited until the separate privacy and security P0 controls are completed.

---

## DEC-096 — Privacy-Minimized AI and Pilot Persistence Boundary

**Status:** Accepted
**Date:** 2026-08-12

### Decision

Inbound customer mail must pass through a deterministic privacy transform before
it can be sent to an AI parser or stored in the pilot evidence database.

The transform creates a SHA-256 fingerprint of the original body, removes common
signature blocks, and redacts personal email addresses, Turkish-format phone
numbers, and Turkish IBAN values while preserving operational freight facts.

Only the privacy-transformed body is stored in `ShipmentExtractionProposal`.
The raw body is not stored in the MINAI pilot SQLite database. The canonical
sender address may be retained because P0.4 customer identity verification needs
it; the sender display name is discarded at the pilot persistence boundary.

`parse_email_with_ai` accepts only `PrivacySafeText`. Passing a normal/raw string
fails closed before any OpenAI API call.

Pilot SQLite evidence has an enforced retention period. The default is 30 days,
configurable with `MINAI_PILOT_RETENTION_DAYS` between 1 and 365 days. Expired
current-state records and audit events are purged when the store initializes and
may also be purged explicitly.

This code-level boundary does not by itself approve use of real company data.
OpenAI account/data-control eligibility, deployment isolation, operator
authentication, contractual/legal requirements, and customer consent or notice
remain separate deployment decisions.

### Consequences

* Raw inbound bodies are no longer duplicated into MINAI durable pilot storage.
* AI parsing cannot accidentally bypass the privacy transform through the normal
  parser entry point.
* Evidence can still be correlated to the source message by irreversible body
  fingerprint plus provider/message metadata.
* Privacy transformation is intentionally conservative: freight-relevant
  company, route, cargo, address, equipment, date, weight, GTIP, and ADR facts
  remain available to the parser.
* Regex minimization reduces exposure but is not a guarantee of full
  anonymization.


---

## DEC-097 — Authenticated and Isolated Shadow-Pilot API Profile

**Status:** Accepted
**Date:** 2026-08-13

### Decision

MINAI shadow-pilot deployments use an explicit `MINAI_PILOT_MODE` access
profile. Pilot mode fails closed unless named operators, private/loopback
network CIDRs, and an explicit private/loopback bind address are configured.

Named pilot operators are configured with unique bearer tokens through
`MINAI_PILOT_OPERATORS_JSON`. Tokens must contain at least 32 characters.
Authenticated token identity is authoritative for human extraction confirmation,
supplier RFQ approval, and quote approval; a request body cannot impersonate a
different operator in pilot mode.

Pilot mode exposes only a small workflow allowlist. Development, simulation,
customer-memory mutation/import/restore, supplier mail send, automated supplier
response ingestion, quote-send preparation, test-suite, and validation/admin
surfaces remain disabled even for authenticated pilot operators.

The health endpoint is authentication-exempt but remains subject to the pilot
network boundary. Requests outside configured private/loopback networks fail
closed. Disabled routes return 404 to avoid advertising non-pilot capabilities.

This is a controlled single-tenant pilot security profile, not a production
identity platform. Production-grade SSO, RBAC, secrets management, reverse-proxy
trust, tenant isolation, and enterprise audit integration remain future work.

### Consequences

* Anonymous access cannot enter the pilot operational workflow.
* Human evidence records use the authenticated operator identity.
* Risky simulation/admin/mutation/send routes are unavailable in pilot mode.
* The same development API can remain available when pilot mode is explicitly
  disabled.
* Network exposure still depends on deployment correctly using the declared bind
  address and allowed private/VPN CIDRs; deployment verification remains part of
  the pilot readiness gate.


---

## DEC-098 — Shadow-Pilot Operational Data Provenance

**Status:** Accepted
**Date:** 2026-08-13

### Decision

MINAI distinguishes operational datasets from internal reference and demo data
through `data/provenance_registry.json`.

Operational data may influence a shadow-pilot workflow only when its provenance
classification is `pilot_verified`, `pilot_usable` is true, the verifying person
and verification time are recorded, and the SHA-256 fingerprint of the current
dataset exactly matches the fingerprint recorded at verification time.

Changing the dataset after verification invalidates that provenance and the
pilot workflow must fail closed until the new dataset version is reviewed and
verified again.

Current supplier capability and customer-memory datasets are explicitly
classified as demo/unverified. Demo supplier data may remain usable for
development and regression testing but cannot drive pilot RFQ selection.
Unverified customer-memory data is ignored in pilot mode and therefore cannot
silently influence enrichment or risk decisions.

Internal commodity and HS/GTIP reference mappings may remain available as
non-authoritative internal reference material. Their presence must not be
represented as external regulatory, customs, or legal verification.

### Consequences

* A provenance label alone cannot authorize operational pilot data.
* Verification is bound to the exact dataset bytes by SHA-256.
* Demo supplier records cannot produce real pilot RFQ drafts.
* Unverified customer memory cannot influence pilot risk decisions.
* Updating verified operational data requires a new review, timestamp, verifier,
  and fingerprint.


---

## DEC-099 — Retry-Safe Durable Provenance Failure State

**Status:** Accepted
**Date:** 2026-08-13

### Decision

Operational resume boundaries record provenance failures as an explicit durable
`data_provenance_blocked` attempt rather than as successful completion or an
unclassified exception.

Extraction and supplier-quote resume operations use explicit attempt states.
An attempt moves to `in_progress` before downstream processing, to
`provenance_blocked` when required provenance cannot be verified, and to
`completed` only after normal processing succeeds. A provenance-blocked attempt
may be retried after the registry or verified dataset is repaired. An in-progress
or completed attempt cannot be started again.

The provenance check remains ahead of RFQ or quote artifact creation. Blocked
results expose only a stable operator-safe reason; registry paths, parser details,
and raw exception text are not part of the operational API result.

### Consequences

* A malformed, missing, stale, or unreadable provenance source cannot strand a
  confirmed extraction in an unclassified started state.
* Repairing provenance permits the same durable extraction or RFQ workflow to
  continue without bypassing verification.
* Completed retries are protected against duplicate downstream artifact creation.
* Durable attempt state does not provide multi-record transactionality; that
  remains a separate concern.


---

## DEC-100 — Atomic Pilot-Critical SQLite Transitions

**Status:** Accepted
**Date:** 2026-08-13

### Decision

Pilot-critical business transitions that update multiple SQLite records use one
short transaction on their shared `SQLitePilotStore`. Repository writes join the
active store transaction and do not independently commit it.

RFQ workflow creation commits its linked workflow and complete draft set
together. Supplier response acceptance commits the response, RFQ lifecycle
state, and inbound-message deduplication marker together. Quote progression
commits the approval, quote case, and completed workflow state together.
Confirmed extraction resume defers newly generated RFQ persistence so those
records, resume evidence, and the completed proposal state also commit together.
Approval decisions continue to update one approval state record; that state and
its append-only evidence event remain one atomic store write because quote-case
snapshots are not rewritten by the decision service.

Validation, computation, AI work, network access, and external outbound activity
remain outside database transactions. Direct nested store transactions are
rejected; workflow helpers may join an already active transaction on the same
store without committing it.

During side-effect-free computation, durable resume state remains retryable.
Before final writes, the short transaction re-reads and compares the durable
attempt state used for computation. A stale concurrent attempt fails its
transition before writing artifacts or evidence. This supersedes only the
pre-computation write mechanics described by DEC-099; its fail-closed legacy
`in_progress` handling and completed-state protections remain unchanged.

### Consequences

* A crash or persistence error exposes either the complete transition or none of
  its constituent durable writes.
* Retrying a rolled-back transition behaves as though its failed attempt never
  committed.
* Repositories participating in one atomic transition must share the same
  SQLite store.
* This decision does not introduce distributed transactions or make external
  provider operations transactional.


---

## DEC-101 — One Fail-Closed Shadow Pilot Launcher

**Status:** Accepted
**Date:** 2026-08-13

### Decision

The controlled shadow pilot starts only through `python -m src.pilot_launcher`.
Before Uvicorn is invoked, the launcher requires pilot mode, validates the
existing pilot access configuration, and validates the optional pilot port. It
passes the validated explicit private or loopback bind address unchanged to the
single ASGI target `src.api:app`.

The launcher fixes reload off and disables proxy headers and forwarded-address
trust. It does not configure outbound email. Development Uvicorn and Streamlit
commands are not pilot-approved startup paths.

### Consequences

* Missing, disabled, malformed, wildcard, public-bind, or invalid-port pilot
  configuration fails before requests can be served.
* Deployment must supply the real listen address rather than relying on a
  wildcard fallback.
* Any future proxy deployment requires a separate explicit security decision;
  forwarded headers are not trusted by this launcher.


---

## DEC-102 — Authenticated Manual Supplier RFQ Send Evidence

**Status:** Accepted
**Date:** 2026-08-13

### Decision

MINAI does not transmit supplier RFQs in the controlled pilot. After an RFQ is
approved and sent outside MINAI through the real logistics operation, the
bearer-authenticated pilot operator may record that manual send. The record
moves the RFQ to `awaiting_response`, allowing subsequent supplier response
ingestion, and stores the operator and timestamp as durable evidence.

For SQLite persistence, the RFQ state and append-only manual-send evidence are
written in one transaction after the current approved state is re-read. No
network, provider, portal, SMTP, or other outbound operation participates in
the transition.

### Consequences

* A body-supplied identity cannot override the authenticated pilot operator.
* Repeated or stale attempts fail and cannot duplicate manual-send evidence.
* A persistence failure rolls back both the lifecycle update and its evidence.


---

## DEC-103 — Minimal Authenticated Pilot Operator CLI

**Status:** Accepted
**Date:** 2026-08-13

### Decision

The controlled pilot uses `python -m src.pilot_operator` as its minimal
operator-facing workflow. The CLI calls only existing pilot-approved API routes,
uses the bearer token from the process environment, restricts destinations to
localhost or explicit private/loopback IPs, refuses redirects, and does not
inherit environment proxy configuration.

The CLI exposes lifecycle reads and approved human transitions but no supplier
or customer automated-send action. It does not access SQLite directly. Existing
read/list API routes and identifiers returned by workflow actions provide
interruption recovery without adding another API surface.

### Consequences

* Operators need not construct raw HTTP requests or inspect the database.
* Tokens are neither command arguments nor persisted client state.
* State changes are not silently retried; operators re-read durable state after
  interruption or conflict.

## DEC-104 — External Coherent Pilot Operational Data Pack

**Status:** Accepted
**Date:** 2026-08-15

### Decision

Gerçek controlled shadow pilot için `customer_memory`, `supplier_capabilities`
ve bunların `provenance_registry` kaydı Git repository dışında tek coherent
operational data pack olarak tutulacaktır.

Pack root yalnız local/deployment environment üzerinden seçilir:

```text
MINAI_PILOT_DATA_DIR=/approved/external/minai-pilot
```

Zorunlu layout:

```text
<MINAI_PILOT_DATA_DIR>/
└── data/
    ├── customer_memory.json
    ├── supplier_capabilities.json
    └── provenance_registry.json
```

Controlled pilot launcher external pack root olmadan başlamaz. Repository
içindeki demo/default operational data development için korunur ancak real
pilot launcher fallback'i değildir.

Readiness assessment ve production API aynı environment-resolved
`OperationalDataSources` paketini kullanır. Extraction resume ve supplier RFQ
quote progression aynı source set'i taşır. Remote HTTP request'leri operational
filesystem path seçemez veya override edemez.

### Rationale

Gerçek müşteri/tedarikçi master data'yı Git history'ye koymak privacy,
operational confidentiality ve lifecycle açısından uygun değildir. Aynı
zamanda readiness'in bir dataset'i doğrulayıp runtime workflow'un başka bir
dataset kullanması kabul edilemez.

Pack-root + `data/` layout mevcut provenance registry path semantiğini korur ve
pack'in approved external storage içinde taşınabilmesini sağlar.

### Safety Properties

- Pack root ve zorunlu dataset dosyaları repository dışında olmalıdır.
- `data/` veya zorunlu dosyaların symlink ile repository içine yönlendirilmesi
  kabul edilmez.
- Eksik veya unsafe pack configuration fail-closed configuration error üretir.
- External pack seçimi provenance authorization yerine geçmez.
- Production provenance validator registered path, consumed path ve exact
  final-byte SHA-256 eşleşmesini korur.
- Demo/unverified operational data gerçek pilot için kullanılabilir hale gelmez.
- Automated outbound policy bu kararla değişmez.

### Consequences

P0.14 gerçek veri geldiğinde repository demo dosyaları yeniden etiketlenmeyecek.
Operasyon sahibi 2–3 gerçek müşteri ve 3–5 gerçek road supplier kaydını external
pack içinde final-byte verification ile hazırlayacaktır. Readiness GO ancak
provenance, sanitized replay ve diğer bütün mandatory approvals birlikte
geçtiğinde mümkün olacaktır.


## DEC-105 — Regression Execution Is CLI-Only

**Status:** Accepted
**Date:** 2026-08-15

### Decision

Controlled pilot regression execution is CLI-only. The production/pilot
FastAPI application must not expose `/run-test-suite` or import regression
evaluators solely for HTTP test execution.

The authoritative regression gate remains
`python -m src.simulation.pilot_regression_suite`.

### Rationale

Regression execution is engineering functionality, not an operational HTTP
capability. Removing it from the API reduces runtime coupling and prevents
test infrastructure from becoming part of the pilot interface.

### Consequences

The HTTP regression route and its regression-only runtime imports are removed.
Authentication, pilot scope, operational data selection, persistence,
business workflows and outbound policy remain unchanged.


## DEC-106 — Supplier Response Simulation Is Outside the Runtime API

**Status:** Accepted
**Date:** 2026-08-15

### Decision

The production/pilot FastAPI application must not expose supplier response
simulation or import the supplier simulator solely to provide an HTTP
simulation endpoint.

Simulation code remains available to engineering regression and rehearsal
workflows outside the operational HTTP surface.

### Rationale

Synthetic supplier responses are development and test functionality. They must
not be confused with operator-entered or ingested real supplier responses.

### Consequences

The `/supplier-rfqs/{rfq_id}/simulate-response` route is removed from
`src.api`. Real supplier response ingestion, RFQ lifecycle, manual-send
evidence, quote progression, authentication, persistence and outbound policy
are unchanged.


## DEC-107 — Controlled Runtime Import and Build Integrity Gate

**Status:** Accepted
**Date:** 2026-08-15

### Decision

The production and controlled-pilot API import graph must not load
`src.simulation` modules, directly or transitively.

Legacy developer simulation and AI test runners must remain outside the
operational workflow import graph.

The canonical pilot gate must also validate that all shipped Python source
files compile successfully.

GitHub Actions must run the locked-runtime preflight, Python source
compilation, canonical pilot regression suite and controlled pilot rehearsal
for pull requests and pushes to `main`.

### Rationale

A green business regression suite does not prove that unused UI or development
code is syntactically valid, nor does a direct-import check detect transitive
runtime coupling to regression infrastructure.

The controlled runtime therefore needs an explicit import-boundary test and an
automated repository build gate.

### Consequences

`src.workflow.pipeline` contains operational workflow behavior only.
Legacy simulation/test execution is isolated under `src.simulation`.
A fresh-process regression verifies that importing the controlled API loads no
simulation modules.
Repository Python syntax is part of the canonical pilot gate.


## DEC-108 — Operational Master Data Must Be Coherent Across One Workflow

**Status:** Accepted
**Date:** 2026-08-15

### Decision

Supplier selection and operational consistency checks within one workflow must
use the same resolved supplier-capabilities dataset.

An external controlled-pilot data pack must contain structurally valid customer
and supplier master data before it is accepted as a runtime data source.

Pilot readiness must require both verified provenance/fingerprint evidence and
valid operational dataset structure.

### Rationale

A supplier selected from one dataset must not later be validated against a
different repository-owned dataset. A correct fingerprint proves exact bytes,
but does not prove that those bytes satisfy the operational schema.

### Consequences

Operational data-source injection now propagates through consistency checks.
External pilot pack resolution fails closed on structurally invalid customer or
supplier master data. Pilot readiness separately reports structurally invalid
verified datasets as blocking.


## DEC-109 — Road RFQ and Supplier Commercial Safety

**Status:** Accepted
**Date:** 2026-08-15

### Decision

Controlled-pilot road RFQ preparation requires sufficient commercial facts:
route countries and locations, foreign postal codes where applicable, positive
gross weight, package count and dimensions, cargo-ready date, and required
delivery date.

Supplier RFQ drafts must carry the operational route, postal code, package and
dimension summary, gross weight, equipment, ready date, required delivery date,
and relevant special notes.

Zero eligible suppliers is an explicit fail-closed workflow state and must not
produce an empty RFQ workflow.

A supplier `needs_clarification` response keeps the same RFQ open. A later
supplier reply may complete that same RFQ.

A quoted supplier price is durable evidence even when commercially incomplete,
but it cannot progress to a customer quote unless all controlled-pilot
commercial safety checks pass. The selected quote must have a parseable transit
duration, valid and unexpired quote date, explicit vehicle availability,
matching equipment, explicit all-in pricing, known included and excluded cost
lists, no excluded charges, and a projected delivery date that satisfies the
customer's required delivery date.

Transit ranges use the conservative maximum stated duration. Hours, calendar
days, business days and weeks are interpreted explicitly rather than treating
all numeric values as days.

### Consequences

Partial, expired, equipment-mismatched, surcharge-dependent or late supplier
quotes remain visible as evidence but are not selectable for customer pricing.

Supplier commercial terms that affect selection are preserved in the selected
supplier quote and quote-approval snapshot so later human approval refers to
the same commercial basis.

Directly recorded supplier responses are manual evidence. Their source cannot
be selected by the HTTP client, and the authenticated operator identity is
stored with the response as `recorded_by`.


## DEC-110 — Pilot Trust, Cardinality and Privacy Hardening

**Status:** Accepted
**Date:** 2026-08-15

### Decision

Controlled shadow-pilot customer profiles use explicit sender trust as identity
evidence. Trusted sender addresses and domains must be syntactically valid and
must not create cross-customer identity ambiguity.

Supplier RFQ contact email addresses must not be shared across different
supplier identities. An inbound supplier response remains bound to the exact
recipient contact stored on its RFQ, including clarification follow-up replies.

Real shadow-pilot readiness requires 2–3 active customer profiles and 3–5 active
supplier profiles. Every active pilot customer must have sender-trust evidence,
and every active pilot supplier must have exactly one usable active primary RFQ
contact.

Inbound privacy minimization covers international-format phone numbers and
IBANs in addition to Turkish formats. Quoted historical mail threads are removed
before AI processing when a deterministic reply delimiter is present.

### Consequences

Operational master data may remain structurally valid outside pilot readiness,
but insufficient pilot coverage, missing sender trust, or missing primary
supplier contacts block REAL SHADOW PILOT GO.

Sender identity is not inferred from message body text, supplier names, or AI
parser output. Privacy transformation continues to occur before any AI parser
call.


## DEC-111 — Runtime Reliability and Private Transport Hardening

**Status:** Accepted
**Date:** 2026-08-16

### Decision

Customer email AI extraction uses an explicit 30-second request timeout and one
SDK retry. Provider/API failures do not expose raw provider error details through
the controlled HTTP endpoint.

When a normalized inbound message has an external message ID, MINAI checks
durable extraction proposals before invoking AI. Re-delivery of the same message
reuses the existing extraction proposal. Reuse of the same message identity with
different body content or sender identity fails closed. Messages without an
external message ID remain processable but cannot receive this provider-level
deduplication guarantee.

Inbound provider-neutral mail bodies are limited to 256 KiB of UTF-8 text before
AI processing.

On POSIX pilot hosts, SQLite pilot evidence files are created and maintained
with owner-only file permissions and symlinked database/storage files are not
accepted.

Loopback pilot operation may use HTTP. Any private-network/non-loopback pilot
binding requires externally stored TLS certificate/key files, and authenticated
private-network requests must use HTTPS. The operator client refuses to send
bearer credentials to a private-network plaintext HTTP URL.

### Consequences

Transient AI/provider failures remain retryable without fabricating shipment
facts. Duplicate provider delivery cannot create repeated successful AI
extractions in the single-process controlled pilot runtime.

Private-LAN pilot operation now requires TLS provisioning before startup.


## DEC-112 — Customer Quote Emails Are Fully Operator-Editable

**Status:** Accepted
**Date:** 2026-08-16

### Decision

AI-generated customer quotation emails are starting drafts, not authoritative final messages.

Authenticated operations personnel may freely revise the complete customer-facing email, including subject, greeting, tone, formality, wording, paragraph structure, explanations and closing. The operator may also explicitly replace the structured customer sales price. Supplier source facts remain unchanged.

Every edit creates a durable revision with before/after email and customer-quote snapshots, operator identity, changed fields and consistency warnings. A revision supersedes a pending or approved approval and creates a fresh pending approval for the exact revised email. Rejected or invalidated quotes may enter a new revision cycle without rewriting historical decisions.

Consistency warnings are advisory: they surface commercial differences but do not silently rewrite or prevent the operator's customer-facing wording. Revision never triggers autonomous outbound email delivery.

### Consequences

The final customer communication is operator-owned while MINAI remains the drafting and consistency assistant. Customer-specific communication-style learning may be added later from revision history.

## DEC-113 — Verified Pilot Data Packs Are Immutable

**Status:** Accepted
**Date:** 2026-08-16

### Decision

Real controlled-pilot customer and supplier master data remains outside the repository and is prepared through the external pilot data-pack workflow.

Before verification, guided customer and supplier intake validates each candidate dataset with the existing production structural validators before atomically replacing the external file. Guided listing must not expose trusted customer sender addresses or supplier contact email addresses.

Verification requires explicit final human review and records fingerprints for the exact final customer and supplier bytes. Once a provenance registry exists, the data pack is frozen: guided intake and verification must refuse in-place changes or replacement of the verification registry.

Any later operational-data change requires a new data-pack version, fresh human review, new SHA-256 fingerprints and fresh provenance verification.

### Consequences

A previously verified pilot pack cannot be silently edited and re-certified in place. Operational master-data corrections are explicit new verification events rather than mutations of already approved evidence.

## DEC-114 — Sensitive Pilot Contact Inputs Are Interactive

**Status:** Accepted
**Date:** 2026-08-16

### Decision

Trusted customer sender addresses, trusted sender domains and supplier primary RFQ contact email addresses must not be supplied as pilot data-pack command-line arguments.

The guided intake CLI requests these values interactively using hidden terminal input. Programmatic core intake functions remain injectable for deterministic regression testing, but the supported human CLI does not place these contact values in shell command history.

### Consequences

Pilot contact identity evidence is still stored in the external operational data pack where required, but the supported intake workflow avoids creating an unnecessary copy in shell history. Listing output continues to expose counts and operational summaries rather than contact addresses.

## DEC-115 — Authorized Sanitized Historical Replay and Commit-Bound Evidence

**Status:** Accepted
**Date:** 2026-08-16

### Decision

Historical replay execution is separated from the provider-neutral offline replay harness.

The supported execution boundary is:

    python -m src.simulation.authorized_sanitized_replay

It may call the production AI parser only when all of the following are explicit:

- the replay JSONL is pre-sanitized and stored outside the repository;
- organizational/legal approval exists for the configured OpenAI data use;
- supplier and customer autonomous outbound remain disabled;
- the external pilot operational data pack is selected and production provenance/structure checks pass.

AI extraction output is evidence to be scored. It is not treated as an operationally confirmed shipment. Downstream workflow replay uses the historical operator-confirmed expected facts as the human-confirmed ground truth, preserving the production extraction-confirmation boundary.

If required safety truth is unknown, replay stops at extraction confirmation rather than inventing a negative safety value.

The execution CLI may optionally write a replay evidence receipt to an absolute external path. Receipt creation requires a clean Git worktree and binds the evidence to:

- the exact 40-character Git commit SHA;
- SHA-256 of the pre-sanitized replay input;
- SHA-256 of the verified customer-memory dataset;
- SHA-256 of the verified supplier-capabilities dataset;
- the active privacy-transform version;
- safe aggregate replay metrics and safety-critical mismatch count.

Replay input and operational dataset fingerprints are checked before and after execution. If they change, receipt creation fails closed. Existing receipt files are never overwritten.

The receipt intentionally records the customer identity mode as pseudonymous replay evidence and does not claim trusted-sender/customer-memory identity verification.

### Consequences

- The offline replay harness remains provider-neutral and network-safe.
- Live-provider replay requires explicit human confirmations and verified external operational data.
- AI extraction cannot bypass the mandatory human extraction-confirmation architecture.
- Replay evidence can be tied to the exact code and operational reference data used.
- A mutated replay input or operational dataset cannot silently produce a valid receipt.
- Receipt output contains aggregate evidence rather than case, sender, customer, or raw-message values.
- A passing replay receipt is technical evidence only; it does not replace organizational, legal, privacy, deployment, operator, reviewer, retention, or pilot GO approval.

## DEC-116 — Approved Customer Quote Final Output Is a Manual Handoff

**Status:** Accepted
**Date:** 2026-08-18

### Decision

In the controlled shadow pilot, the final customer quotation output is a
read-only manual handoff rather than an outbound delivery action.

A final output may be produced only for the current `QuoteCase` when its current
approval record is loaded from durable approval storage and the existing quote
send-safety evaluation confirms that the approval is valid for the exact current
supplier quote, customer quote and customer-facing email snapshot.

The final output contains the exact approved customer-facing subject and body,
structured final customer price and currency, approval identity and timestamp,
and current revision number. Its delivery mode is explicitly
`manual_external_operation`, and `automated_send_performed` is always false.

Any customer-quote revision supersedes the previous approval authority. A
previously approved version cannot authorize the revised quote. The revised
version remains unavailable as final output until its fresh current approval is
approved and matches the revised quote snapshot.

The controlled-pilot operator interface exposes this boundary as a read-only
`case final` action. It does not expose customer SMTP, provider delivery,
automatic quote sending or any other autonomous customer outbound action.

### Consequences

The operations person receives one explicit, unambiguous approved customer quote
to copy into the authoritative external logistics email system.

MINAI remains the drafting, revision, approval and consistency assistant while
the real logistics operation remains authoritative for customer delivery.

A successful technical send-safety evaluation does not itself perform or prove
delivery. Final customer delivery remains an external human-controlled
operational action.

Editing an approved quote intentionally removes the previous version's delivery
authority and requires a new human approval before a new final manual handoff can
be produced.

## DEC-117 — Readiness Evidence Is Commit- and Operational-Data-Bound

**Status:** Accepted
**Date:** 2026-08-18

### Decision

Real shadow-pilot readiness evidence uses schema version 2 and must bind
authorized sanitized historical replay evidence to both the exact release
commit and the exact verified operational master data used by that replay.

Readiness evidence therefore records SHA-256 fingerprints for:

- `customer_memory`;
- `supplier_capabilities`.

Those fingerprints must exactly match the currently configured verified
external pilot data pack.

A replay receipt produced against one verified data pack cannot authorize
readiness against another data pack, even when both use the same Git commit.

Legacy schema version 1 readiness evidence is rejected because it does not
contain this operational-data binding.

The supported operator workflow is:

    python -m src.pilot_readiness_evidence build

The guided builder:

- accepts an external authorized replay receipt;
- requires a clean Git worktree;
- verifies the exact current Git commit;
- verifies the current operational dataset fingerprints;
- requires a passing replay with at least one case;
- requires zero safety-critical replay mismatches;
- records the seven independent human attestations interactively.

Each attestation requires the exact confirmation word `CONFIRM`, a non-empty
confirming role or person, and a timezone-aware timestamp.

The builder records approvals that already exist. It does not itself grant an
approval, perform legal review, authorize the pilot, or start the real shadow
pilot.

Generated readiness evidence must be written to an absolute external
create-only path. Existing evidence files are not overwritten.

Raw replay cases, customer or supplier records, message content, secrets and
credentials are not copied into readiness evidence.

### Rationale

Commit binding alone is insufficient for controlled-pilot evidence.

Without operational-data fingerprint binding, replay evidence generated
against verified data pack A could theoretically be combined with readiness
assessment against verified data pack B when both use the same Git commit.

Readiness evidence must therefore identify both the exact code and the exact
operational reference data for which the replay evidence was produced.

Manual transcription of replay summaries and operational-data fingerprints
also creates an avoidable evidence-integrity risk. The guided builder derives
those values from the validated replay receipt and verified operational data
instead.

### Consequences

A changed customer-memory or supplier-capability dataset requires a newly
verified pilot data pack and fresh replay evidence before REAL SHADOW PILOT GO
can be reached.

Replay evidence from one verified pack cannot be reused against another pack.

Operators no longer manually construct readiness JSON or manually transcribe
the replay result into the human-attestation file.

Readiness evidence remains an evidence record, not an approval mechanism.

Organizational, privacy/legal, OpenAI data-control, deployment/storage,
retention/deletion, named-operator and senior-road-reviewer approvals remain
independent human prerequisites.

Automated supplier RFQ and customer quote outbound remain disabled for the
controlled shadow pilot.

## DEC-118 — Outlook Inbound Is Delegated Read-Only and Human-Gated

**Status:** Accepted
**Date:** 2026-08-19

### Decision

The controlled shadow pilot may ingest customer inquiry email directly from one
approved Microsoft 365 / Outlook mailbox through Microsoft Graph.

Microsoft authorization uses a delegated public-client flow with the minimum
`Mail.Read` permission. The pilot does not request `Mail.ReadWrite`,
`Mail.Send`, application-wide mailbox access, or a Microsoft client secret.

The initial authorization or later reauthorization is an explicit host-side
device-code action. Normal inbox pulls use silent server-side authentication
from an external token cache. The token cache must be stored outside the
repository and must be owner-only on POSIX systems.

Microsoft access tokens and refresh-token material are never transferred to the
MINAI operator client, included in pull results, or printed by normal operator
workflow output.

The provider adapter is read-only. It lists inbox messages through HTTP GET,
requests immutable Microsoft Graph message IDs and text message bodies, refuses
redirects, and bounds each explicit pull to at most 50 messages.

P1-19 does not mark messages as read, move, delete, flag, reply to or send mail.
It does not introduce Graph subscriptions, webhooks, background mailbox polling
or autonomous mailbox monitoring.

Microsoft Graph provider identity is created only by the server-side adapter.
The existing manual `/process-email` path remains `source=manual` and cannot
assert Microsoft Graph provenance.

Before any Outlook message can reach the AI parser, the controlled inbound gate
requires:

- complete Microsoft Graph provider metadata;
- no attachments;
- a currently verified external pilot customer-memory dataset;
- an active customer profile;
- exactly one trusted-sender address/domain match.

An untrusted sender, ambiguous customer match, unsupported attachment, missing
pilot operational data, or unverifiable provenance stops before AI extraction.

For an allowed message, the existing privacy transform runs before the
production AI parser. The parser still creates only a non-authoritative
extraction proposal. Explicit human extraction confirmation remains mandatory
before the shipment may enter the operational workflow.

Inbound idempotency uses provider identity, mailbox identity and the immutable
external message ID. Re-reading an identical message reuses the existing
proposal without another AI parse. Reuse of the same message identity with
different content or sender is fail-closed.

The operator-facing pull response is deliberately minimized. It may expose the
immutable external message ID, received timestamp, safe result state/reason and
proposal ID. It must not expose the raw customer body, sender address, Microsoft
token material or provider error payload.

### Rationale

Manual copy/paste of every customer inquiry creates avoidable operator effort
and transcription risk, but giving MINAI mailbox write or send authority would
expand the controlled-pilot autonomy boundary unnecessarily.

Delegated read-only Graph access closes the inbound operational gap while
preserving the existing privacy, identity, extraction-confirmation, provenance
and human-approval controls.

Trusted-sender filtering must occur before AI use because the controlled pilot
is limited to explicitly approved customers. Reading a message from the mailbox
is not itself sufficient evidence that its content is authorized for AI
processing.

Attachments remain outside the automated P1-19 boundary because interpreting
them would add a materially different file-ingestion and content-safety surface.

### Consequences

The operator can explicitly pull real approved customer inquiries from Outlook
without manually copying the normal message body into MINAI.

The Outlook integration is still operator-triggered and inbound-only. It does
not make MINAI an autonomous mailbox agent.

Messages outside the verified pilot-customer scope do not reach the AI parser.

Messages with attachments require manual review outside this automated inbound
path until a separately designed attachment-ingestion boundary exists.

Repeated pulls do not cause repeated extraction of the same immutable Outlook
message.

Loss or expiry of delegated Microsoft authorization blocks Outlook pulling and
requires explicit reauthorization; it does not fall back to a broader
permission.

The existing manual inbound path remains available as an explicitly manual
fallback and cannot impersonate Graph-originated mail.

Supplier RFQ delivery and customer quotation delivery remain manual external
operations. P1-19 adds no autonomous outbound capability.

## DEC-119 — Outlook Supplier Replies Use Deterministic Pre-AI Routing

**Status:** Accepted
**Date:** 2026-08-19

### Decision

The controlled shadow pilot may ingest supplier RFQ replies through the same
explicit delegated read-only Microsoft Graph inbox pull introduced by P1-19.

A Graph message does not reach a supplier-response AI parser merely because its
text appears to be a quotation. Supplier authority and RFQ authority are
deterministic system concerns and must be established before AI use.

Before supplier AI extraction, MINAI requires the existing RFQ correlation and
lifecycle checks to establish a single eligible RFQ and the expected supplier
sender identity. Conflicting customer/supplier authority, ambiguous RFQ
correlation, unknown senders, unsupported attachments or invalid Graph
provenance fail closed before AI.

After deterministic supplier/RFQ correlation succeeds, the approved inbound
privacy transform runs on the supplier body. The production supplier-response
parser accepts PrivacySafeText only.

Supplier AI authority is restricted to structured commercial response fields.
It cannot select or mutate the supplier identity, RFQ identity, customer,
workflow or lifecycle state.

A validated supplier response may be durably attached to the already-correlated
RFQ. Immutable provider/mailbox/message identity provides inbound idempotency so
the same Outlook message cannot create a second response.

The existing explicit operator Outlook pull remains bounded and read-only. Its
summary may expose safe routing state, RFQ ID and deterministic correlation
method, but does not expose the raw supplier body, sender address, commercial
price payload, Microsoft token material or provider error body.

A production supplier-parser availability failure stops the current bounded pull
as partial_parser_unavailable rather than silently degrading into an uncertain
commercial result.

P1-20 does not automatically resume quote progression after a response is
attached. It also does not send supplier RFQs or customer quotes, write to the
mailbox, mark messages as read, move/delete/flag messages, create subscriptions
or add background polling.

### Rationale

Supplier replies are part of the Phase 1 email-to-quote workflow, but allowing
AI to decide which supplier or RFQ a message belongs to would give model output
lifecycle authority it must not have.

The existing deterministic RFQ reference, sender continuity, lifecycle and
duplicate protections already provide the authoritative boundary. Reusing
those controls for Graph-originated replies closes the inbound supplier gap
without broadening mailbox or outbound permissions.

The same privacy boundary used before customer AI extraction should also apply
to supplier commercial extraction. Contact details, signatures and unrelated
quoted-thread material do not need to cross the AI boundary merely to extract a
rate.

### Consequences

One explicit Outlook pull can safely route both approved customer inquiries and
deterministically correlated supplier replies.

Customer/supplier identity overlap and ambiguous supplier correlation require
manual review instead of guessing.

Supplier commercial responses can enter durable RFQ state without manual
copy/paste, while quote progression and all outbound delivery remain under the
existing human-controlled workflow.

Attachments remain outside automated ingestion until a separately designed
attachment boundary exists.

The P1-20 implementation and canonical regressions are deterministic/offline.
No live Microsoft tenant/mailbox supplier-response network pull is claimed by
this implementation pass. A live approved pilot tenant must be validated
separately before operational reliance.

## DEC-120 — Live Outlook Validation Requires Commit-Bound Two-Pass Evidence

**Status:** Accepted
**Date:** 2026-08-19

### Decision

P1-21 introduces a controlled live Microsoft Outlook smoke-validation
procedure for the approved pilot mailbox.

Live Outlook validation is not represented by a successful network request
alone. Technical evidence is accepted only when all of the following are true:

- the local release worktree is clean;
- the running pilot API exposes the same startup commit SHA through the
  authenticated `/runtime/release` route;
- the live Microsoft tenant and mailbox use the existing delegated
  `Mail.Read`-only integration;
- explicit human confirmations exist for live-tenant authorization,
  configured OpenAI data use, preparation of the four controlled smoke
  messages, and continued prohibition of autonomous outbound;
- the first Outlook pull identifies exactly one controlled case for each
  required scenario;
- the second pull verifies deterministic replay/idempotency for the same
  immutable Microsoft Graph message IDs;
- the resulting evidence receipt is create-only, stored outside the
  repository, and contains no mailbox identity, sender identity, raw message
  body, Microsoft token, Graph message ID, proposal ID, RFQ ID, or commercial
  response payload;
- mailbox writes and automated sends remain false.

The four required live smoke scenarios are:

1. trusted customer inquiry routes to the customer extraction-proposal path;
2. known supplier reply routes to the already-correlated supplier RFQ path;
3. wrong/untrusted supplier sender fails closed before AI;
4. message with attachments requires manual review and does not send the
   attachment to AI.

### Route-History Integrity

An immutable Outlook message already consumed through the customer route must
remain a customer replay even if later supplier/RFQ state would cause a new
current-state supplier correlation.

Likewise, an immutable message already consumed through the supplier route
must remain a supplier replay.

Reuse of the same immutable message identity with different body content or
sender identity fails closed.

If durable evidence says the same immutable message was previously consumed
through both customer and supplier routes, processing fails closed as an
idempotency conflict.

Historical route evidence therefore takes precedence over later mutable
routing state.

### Runtime Identity

The pilot API captures release identity once at process startup.

`GET /runtime/release` is available only inside the authenticated pilot
boundary. It exposes only:

- whether repository identity was available;
- the startup commit SHA;
- whether the startup worktree was clean.

It exposes no secret, token, mailbox, customer, supplier, or message data.

The live smoke runner refuses to execute if the server startup commit and
the clean local release commit differ.

### Evidence Boundary

The first live pass writes an external private manifest containing the four
immutable Graph message identifiers. That manifest is operationally sensitive
and must remain outside the repository with owner-only permissions where the
platform supports them.

The final receipt does not reproduce those identifiers. It stores only:

- pilot commit SHA;
- manifest SHA-256;
- timestamp;
- aggregate scenario pass/fail status;
- safe pull counts/status;
- explicit confirmation flags;
- no-mailbox-write and no-automated-send invariants.

A passing receipt is technical integration evidence only. It does not replace
organizational approval, privacy/legal approval, Microsoft tenant
administration, OpenAI data-use approval, operational-data verification,
retention/deletion procedures, or human workflow controls.

### Out of Scope

P1-21 does not add:

- `Mail.ReadWrite`;
- `Mail.Send`;
- mailbox marking, moving, deleting, flagging, replying, or sending;
- webhooks or subscriptions;
- background polling or autonomous monitoring;
- autonomous supplier RFQ delivery;
- autonomous customer quotation delivery;
- automatic quote progression after supplier-response ingestion.

Until a live tenant run produces a passing commit-bound receipt, Outlook live
integration remains implemented but not live-pilot-validated.

## DEC-121 — Live Smoke Manifest Must Remain Stable During Execution

**Status:** Accepted
**Date:** 2026-08-19

### Decision

The P1-21 private manifest is treated as immutable evidence input for one
live smoke execution.

The runner reads and hashes one exact manifest byte snapshot before the live
Outlook pull. After the network execution and before receipt creation, it
re-reads the protected external manifest and verifies that its SHA-256 is
unchanged.

If the manifest changes during execution, the run fails closed with
`outlook_smoke_manifest_changed_during_execution` and no receipt is created.

The final receipt is bound to the SHA-256 of the exact manifest snapshot that
was parsed for routing verification, not to a later independently read version.

This closes the time-of-check/time-of-use gap between manifest parsing,
live network execution, and evidence receipt creation.

## DEC-122 — Remove Human-Obvious Road Workflow Stops

**Status:** Accepted
**Date:** 2026-08-28

### Decision

MINAI road workflows must distinguish genuinely missing operational facts from
facts an experienced operator can resolve safely from trusted identity,
explicit direction, explicit road language and message-relative timing.

The trusted inbound sender identity is carried into downstream customer memory.
Import/export Türkiye endpoint inference is symmetric. Explicit road language
may establish road mode. Relative `today/tomorrow/ready/immediately` language
may be resolved against message time when positive and unambiguous.

`high_value_candidate` remains a candidate/review signal and is not confirmed
high-value source truth. Non-critical commodity questions remain advisory.
Supplier country capability for Türkiye international lanes is symmetric for
import/export to the same supported foreign country, without creating arbitrary
foreign-to-foreign authority.

A terminal supplier negative response prepares the next eligible supplier RFQ
draft for human approval. A commercially incomplete quoted response reopens the
same RFQ for clarification and prepares a follow-up draft; it does not consume
the RFQ permanently.

### Safety Boundary

These changes reduce redundant manual work but do not authorize automatic RFQ
or customer-quote sending, bypass sender trust, weaken explicit customer
delivery deadlines, or overwrite contradictory source facts.

## DEC-123 — Turkish Road Commercial Defaults and Indicative Quote Mode

**Status:** Accepted
**Date:** 2026-08-28

### Decision

For standard Turkish road freight pricing, supplier quote validity and separate
vehicle availability dates are optional. Standard road price is treated as
all-in unless the supplier explicitly states extras/exclusions. Included and
excluded cost lists are not mandatory when no exception is stated. A supplier
reply to the exact RFQ implicitly accepts the requested equipment unless it
explicitly proposes a different one. Transit remains required for a normal firm
road customer quote.

If a validity date is explicitly provided, it is preserved and communicated to
the customer; a parseably expired quote is not used. Explicit extra/excluded
charges, base-freight-plus-extras terms, or equipment mismatch remain commercial
exceptions requiring clarification/review rather than silent normalization.

Customer requests containing explicit `indikatif` / `indicative` intent use a
separate `quote_mode=indicative`. Indicative pricing is non-binding budgetary
pricing for a future/not-yet-firm move. Route-level information may be enough;
firm shipment details such as exact weight, dimensions and ready date are not
mandatory solely for indicative pricing. Supplier RFQs and customer output must
both disclose the non-binding nature. A future real shipment requires fresh
firm-price confirmation and vehicle-availability confirmation.

## DEC-124 — Profitability Is Agency Policy, Not a MINAI Constant

**Status:** Accepted
**Date:** 2026-08-28

### Decision

Customer-quote profitability is not a universal MINAI business rule. Each
freight agency may have its own pricing policy, and profitability may also vary
for an individual quote.

The production product must support an agency-level default profitability
setting and an explicit quote-level override. Future customer-specific pricing
policy may be layered on top without changing the principle that the final
commercial decision belongs to the agency.

The current controlled pilot may continue using a fixed 15% markup solely as a
deterministic test assumption. That 15% value must not be presented or treated
as the final product's mandatory profitability policy.

## DEC-125 — Manual Customer Quote Delivery Requires Durable Evidence

**Status:** Accepted
**Date:** 2026-08-28

### Decision

When an approved customer quote is handed off for manual external sending, MINAI
must be able to record that the operator confirms the send actually occurred.
The record is evidence of a manual action; it does not authorize or claim an
automated send.

Each manual customer-quote send record is bound to the exact quote case,
current approval ID and revision number, and preserves recipient address,
operator identity, send timestamp and `manual_external_send` source. The caller
must provide the expected current approval ID so a stale quote cannot be marked
sent after a revision or approval change.

Send evidence is append-only within the quote case. A later quote revision may
be approved and sent again, but it must create a new evidence record while the
prior delivery record remains auditable.

## DEC-126 — Cargo Value Is a Risk Signal, Not an Automatic Quote Block

**Status:** Accepted
**Date:** 2026-08-28

### Decision

Unknown cargo value does not block a standard road RFQ or customer-pricing
workflow merely to complete a record. MINAI must preserve `is_high_value=None`
until the customer, operator or other authoritative source establishes the fact.

Confirmed high-value cargo is no longer an automatic shadow-pilot scope
exclusion. It becomes an operational review signal for carrier liability limits,
additional cargo insurance where relevant, security conditions and carrier
acceptance. It does not by itself require management approval; an agency-specific
policy may introduce such a threshold later.

Cargo value alone must not silently replace an explicitly requested equipment
type. Supplier capability or insurance constraints may later require a deliberate
operator decision, but high value is not itself a universal Box Trailer rule.


## DEC-127 — Internal Commodity Profile Notes Must Not Leak Into External RFQs

**Status:** Accepted
**Date:** 2026-08-28

### Decision

Commodity-profile notes are internal operational context. Even when they are
carried in the shipment's working `special_notes` field, supplier-facing RFQ
generation must remove `[COMMODITY PROFILE]` lines before creating external
mail content.

Customer- or operator-supplied special notes remain eligible for the supplier
RFQ when commercially relevant. If filtering leaves no external special note,
the RFQ omits the `Özel Notlar` line entirely rather than exposing an internal
placeholder.


## DEC-128 — Price-Only Supplier Replies Are Deterministic; Identity Fallback Is Time-Bounded

**Status:** Accepted
**Date:** 2026-08-31

### Decision

A privacy-minimized supplier reply consisting only of one positive monetary
amount plus a supported ISO currency (`EUR`, `USD`, `GBP`, or `TRY`) is treated
deterministically as a quoted rate. MINAI does not require AI inference to decide
that `2400 EUR` is a quote, and it does not invent any absent transit, validity,
availability, equipment, inclusion, or exclusion fields.

Supplier-address-only RFQ correlation remains a fallback behind explicit and
subject RFQ references. The fallback may consider only RFQs whose recorded send
time is at or before the inbound message's received time. Missing timestamps or
messages predating an RFQ send must not be attached to that later RFQ.

## DEC-129 — Supplier Clarification Follow-Ups Are Durable, Human-Gated Workflow Objects

**Status:** Accepted
**Date:** 2026-08-31

### Decision

A supplier clarification generated after an incomplete but usable RFQ response is
not merely transient mail text. MINAI persists it as a follow-up record linked to
the same RFQ, with its own follow-up ID, sequence number, rejection reasons,
recipient, subject, body and lifecycle state.

Supplier follow-ups require explicit human approval before external sending.
Manual external sends have their own durable evidence and never reuse the initial
RFQ send evidence. A later supplier response closes the active sent follow-up in
the audit trail.

When the supplier answers only the fact requested by the clarification, MINAI may
consolidate that new fact with authoritative commercial fields from the prior
quoted response on the same RFQ. Inherited fields and the prior response timestamp
are recorded explicitly; missing facts are not invented.

For sender-identity fallback during an active clarification, the latest sent
follow-up establishes the temporal lower bound for candidate supplier replies.

## DEC-130 — Supplier Follow-Up Human Gates Must Be Reachable in Pilot Mode

**Status:** Accepted
**Date:** 2026-08-31

### Decision

Durable supplier follow-up read, approval and manual-send-evidence routes are part
of the authenticated shadow-pilot operator surface. They must be available through
the same private-network and bearer-authentication boundary as the parent RFQ.

This does not authorize provider sending. No supplier follow-up automated-send
route is enabled in pilot mode; external delivery remains a separate human action.

## DEC-131 — Latest Supplier Response Snapshot Supersedes Earlier Same-RFQ Quotes in Selection

**Status:** Accepted
**Date:** 2026-08-31

### Decision

Supplier response history remains append-only, but quote comparison and supplier
selection treat only the latest response snapshot for each RFQ as authoritative.
A consolidated clarification reply therefore supersedes the earlier incomplete
quote for commercial comparison without deleting either response from the audit
trail.

The supersession rule is applied before price usability. If a later same-RFQ
response is terminal or requests clarification, MINAI must not resurrect an older
price merely because the older response was quote-usable.

## DEC-132 — Customer Pricing Must Resolve from Explicit Policy, Never a Hidden MINAI Percentage

**Status:** Accepted
**Date:** 2026-08-31

### Decision

Production customer pricing no longer has a hardcoded percentage fallback. Before
MINAI creates a customer quote, it resolves one explicit pricing formula using
this precedence: quote-specific override, verified customer pricing policy, then
agency default pricing policy. If none exists, the workflow returns
`pricing_policy_required` and creates no customer quote case.

Supported formulas are named by their commercial meaning:
`cost_markup_percentage`, `gross_margin_percentage`, `fixed_profit`, and
`manual_sell_price`. Cost markup and gross margin are not interchangeable.

Agency pricing configuration also owns rounding behavior. Rounding may be defined
as an agency default and overridden by currency. A manual sell price is never
silently rounded by MINAI.

The selected formula, policy source, currency and effective rounding rule are
persisted with the customer quote and copied into the approval snapshot. A later
operator price revision is recorded as `manual_sell_price` with
`operator_revision` provenance and requires fresh approval under the existing
revision rules.

The controlled regression suite may continue to use an explicit synthetic 15%
cost-markup fixture. That fixture is test configuration only and is not a runtime
production default.

## DEC-133 — Supplier Ranking and Supplier Dispatch Are Separate Agency Policies

Supplier eligibility and ranking answer **who is suitable and in what order**. Supplier dispatch answers **how many ranked suppliers receive an RFQ in the current batch**. These concerns must remain separate so an agency can preserve its supplier-ranking logic while choosing a sequential or parallel commercial outreach style.

For P1-42, the supported runtime dispatch modes are `sequential` and `parallel`. Sequential dispatch creates an initial RFQ only for priority 1. Parallel dispatch creates initial RFQ drafts for the first configured 2 or 3 eligible suppliers. Every draft remains behind the existing human approval and send boundaries; parallel draft creation does not authorize automatic sending.

The active dispatch policy is snapshotted on `SupplierRFQWorkflow` when the workflow is created. Later agency configuration changes must not silently change the strategy of an already-open supplier workflow.

Hybrid time-based dispatch is intentionally deferred. A future hybrid policy may combine an initial batch with response-time thresholds and later fallback batches, but it must not be represented as implemented until its timeout and scheduling semantics are explicit and tested.

## DEC-134 — Outlook Sending Requires Explicit Delegated Mail.Send and Real Provider Acceptance

**Status:** Accepted
**Date:** 2026-09-01

MINAI may send supplier RFQs and approved customer mail through Microsoft Graph only when the controlled Outlook account has delegated `Mail.Send` permission in addition to `Mail.Read`. Merely creating or approving an outbound draft does not authorize delivery.

The runtime Graph sender uses the existing provider-neutral `OutboundMailSender` boundary. A message is recorded as sent only after Microsoft Graph accepts `/me/sendMail` with HTTP 202. The Graph response request identifier is retained as the provider delivery reference. Authentication or provider failures must leave the workflow unsent.

## DEC-135 — Automated Customer Quote Sending Requires Durable Provider Evidence

**Status:** Accepted
**Date:** 2026-09-01

An approved customer quote may be delivered automatically through the configured outbound mail provider only through a case-aware delivery service that preserves the current approval and revision boundaries. A successful provider call is not enough by itself; MINAI must persist delivery evidence on the quote case so the send remains auditable after restart.

Automated customer quote evidence records the case ID, approval ID, revision number, recipient, provider name, provider delivery reference and provider-confirmed send timestamp. Evidence may be created only when the provider-neutral delivery result is `sent` and includes the required provider metadata.

Manual and automated send evidence are mutually exclusive for the same approval/revision. A second send attempt for an already-sent revision must be rejected before the provider is called. Provider failure must leave the quote case without automated sent evidence.

## DEC-136 — Quote Approval State Must Be Durable on the Quote Case

**Status:** Accepted
**Date:** 2026-09-01

A quote approval transition is authoritative in the approval repository, but any QuoteCase that embeds that approval must also persist the same current approval state. API-time enrichment may remain as a defensive read path, but it must not be the only mechanism preventing stale approval snapshots.

For controlled production approval, rejection and invalidation transitions, the approval repository and related quote-case repository must be updated in one atomic repository transaction when they share the pilot SQLite store. The durable QuoteCase must also persist the send-safety decision derived from the new approval state.

## DEC-137 — Controlled Supplier RFQ Sending Is an Explicit Operator Action

**Status:** Accepted
**Date:** 2026-09-01

The controlled pilot may expose supplier RFQ delivery through `POST /supplier-rfqs/{rfq_id}/send` and the matching `pilot_operator rfq send` command. This surface does not authorize background dispatch: the operator must explicitly invoke the send action for the exact RFQ after its separate human approval transition.

A provider-confirmed supplier RFQ send must persist durable automated-send evidence containing the RFQ ID, recipient, provider name, provider delivery reference and provider-confirmed timestamp. Provider failure or incomplete provider metadata must leave the RFQ approved and unsent. A repeated send for an already-sent RFQ must be rejected before a second provider call.

## DEC-138 — Supplier Send HTTP Success Means Provider-Confirmed Delivery

**Status:** Accepted
**Date:** 2026-09-01

The controlled supplier RFQ send endpoint must not return a successful HTTP response when no provider delivery occurred. A pre-provider lifecycle rejection is a conflict, and a provider failure or unavailable provider is an operational service failure. Only a provider-confirmed `sent` result may return HTTP success.

This keeps the HTTP contract aligned with operator automation: `pilot_operator rfq send` must exit nonzero whenever the requested RFQ was not sent. A safe rejection remains non-destructive, but it is not a successful send operation.

## DEC-139 — Supplier Clarification Follow-Ups Use the Same Controlled Provider Send Contract

**Status:** Accepted
**Date:** 2026-09-01

A Supplier RFQ clarification follow-up may be delivered through the configured outbound provider only after the follow-up has its own explicit human approval and the parent RFQ remains in `clarification_required`. Automated follow-up delivery is an explicit operator action and does not authorize background clarification traffic.

Provider-confirmed follow-up delivery must persist durable evidence containing the follow-up ID, parent RFQ ID, sequence number, recipient, provider name, provider delivery reference and provider-confirmed timestamp. The follow-up may advance to `awaiting_response` only after that provider confirmation. Manual and automated follow-up send evidence are mutually exclusive.

## DEC-140 — Clarification Consolidation Must Clear Resolved Uncertainty

**Status:** Accepted
**Date:** 2026-09-01

When a clarification follow-up resolves a field by deterministic inheritance or consolidation, the resulting SupplierResponseExtraction must not retain that field in `uncertain_fields`. A field may remain uncertain only while its merged value remains absent.

This applies especially to `status`: a prior quoted response plus a valid follow-up commercial fact may resolve the consolidated response to `quoted` even when the follow-up parser itself was uncertain about status. The resolved value and uncertainty metadata must remain internally consistent before validation.

## DEC-141 — Natural Transit-Only Supplier Replies Use Deterministic Extraction

**Status:** Accepted
**Date:** 2026-09-01

Short supplier clarification replies that contain only transit information may be resolved deterministically even when phrased as a natural sentence, for example `Transit süremiz 5–6 gündür.` or `Transit time is 5-6 days.`. These replies must not be sent to the AI parser when the full message is an anchored transit-only expression.

The deterministic path must extract only the transit value itself and must remain narrow enough that replies containing price, capacity, equipment, validity or other commercial facts do not bypass structured parsing.

## DEC-142 — Outlook Attachment Metadata Precedes Attachment Content Processing

**Status:** Accepted
**Date:** 2026-09-01

Before MINAI may interpret Outlook attachment content, the controlled Graph adapter must first establish a provider-neutral attachment manifest containing only bounded metadata: normalized filename, MIME type, byte size and inline state. Attachment IDs, content bytes and provider download references are not part of the inbound envelope.

P1-51 does not authorize attachment content download or parsing. Messages with attachments continue to stop before customer or supplier AI parsing. The manifest exists only to make later attachment allowlisting, size limits and manual-review decisions explicit and auditable.

## DEC-143 — Attachment-Only Outlook Messages Must Preserve the Safe Manifest

**Status:** Accepted
**Date:** 2026-09-01

An Outlook message whose text body is blank may still be a valid attachment-bearing inbound message. When `hasAttachments=true`, the controlled Graph adapter must collect the bounded metadata-only attachment manifest before applying the attachment manual-review gate instead of classifying the message only as an empty-body rejection.

This exception does not relax the general inbound body contract: blank-body messages without attachments remain invalid. Attachment-only messages remain blocked before customer or supplier AI parsing, and attachment content bytes, provider attachment IDs and download references remain outside the provider-neutral envelope.

## DEC-144 — Outlook Non-Empty Body Normalization Must Remain Stable

**Status:** Accepted
**Date:** 2026-09-01

Allowing attachment-only Outlook messages to reach the safe attachment manifest path must not change normalization for ordinary non-empty message bodies. Non-empty Graph text bodies continue to use the established trimmed representation so durable route fingerprints and idempotency remain stable across releases.

An attachment-only message may use an empty provider-neutral body only when `has_attachments=true`; that exception must not alter existing non-empty message identity.


## DEC-145 — Attachment Intake Starts With a Metadata-Only Allowlist

**Status:** Accepted
**Date:** 2026-09-01

P1-54 classifies inbound Outlook attachments using metadata only; it does not authorize attachment content retrieval. A metadata candidate must be a non-inline Microsoft Graph `fileAttachment` whose extension/MIME pair is allowlisted as PDF, XLSX or CSV. Unknown, item or reference attachment kinds remain manual-review-only.

The initial limits are 10 MiB per file, 20 MiB total per message and at most 5 automatically eligible files. Missing or mismatched MIME metadata, unsupported extensions including macro-enabled Office formats, manifest truncation, inline files or any limit breach require manual review. Even an allowlisted metadata result remains blocked at the existing attachment gate until a separate controlled content-retrieval boundary is approved.


## DEC-146 — Attachment Content Retrieval Requires a Verified Inbound Route

**Status:** Accepted
**Date:** 2026-09-01

P1-55 may retrieve raw content only for an attachment set already classified `metadata_allowlisted` by P1-54 and only after deterministic inbound routing identifies exactly one trusted customer or supplier route. Unknown senders, ambiguous customer identity, ambiguous supplier RFQ correlation, customer/supplier overlap, unavailable provenance or metadata-policy failures must not trigger an attachment content request.

After route trust, the Graph integration may make a second attachment-metadata request that includes provider attachment IDs solely as transient in-process locators. The fresh metadata must remain allowlisted and exactly match the original provider-neutral manifest before any `/$value` request is made. Provider attachment IDs must not enter the inbound envelope, durable state, operator summary or verification receipt.

Raw content retrieval is bounded to the existing 10 MiB per-file policy, refuses redirects, requires raw downloaded bytes not to exceed the Graph metadata size and produces only a provider-neutral SHA-256 verification receipt. PDF content must satisfy PDF header/EOF checks; XLSX must be a valid macro-free OOXML ZIP container with required workbook structure; CSV is limited to a UTF-8 text profile because CSV has no universal binary magic signature. P1-55 does not parse business meaning and does not send attachment content to AI. Verified content still returns manual review until a later parsing boundary is approved.


## DEC-147 — Verified Attachments May Be Extracted Only Into Bounded Provider-Neutral Artifacts

**Status:** Accepted
**Date:** 2026-09-01

P1-56 permits deterministic content extraction only after P1-55 has completed trusted-route attachment retrieval and content verification. Raw attachment bytes remain transient inside the Graph integration boundary. Extraction must run before the mutable content buffer is cleared, and only bounded provider-neutral text/table artifacts may cross that boundary.

PDF extraction uses the locked `pypdf` runtime and is limited to 50 pages and 100,000 extracted characters per file. Encrypted PDFs, PDFs with no extractable text, parser failures or limit breaches require manual review. XLSX extraction reads only bounded OOXML worksheet/shared-string XML, never evaluates formulas, and limits a file to 10 worksheets, 200 rows per worksheet, 50 columns, 5,000 non-empty cells and 100,000 extracted characters. Formula-bearing workbooks require manual review. CSV extraction is UTF-8 only, detects a narrow delimiter set, and is limited to 1,000 rows, 50 columns, 5,000 non-empty cells and 100,000 characters.

Extraction artifacts are ephemeral and excluded from default retrieval-result serialization. The controlled operator/API summary may expose only safe aggregate extraction status and counts, never extracted attachment text/table values. P1-56 does not interpret business meaning, does not send attachment content to customer or supplier AI parsers, does not persist extracted content and does not authorize mailbox writes or outbound mail. Successfully extracted attachment mail remains manual-review-only pending a separately approved interpretation boundary.

## DEC-148 — Attachment Interpretation Is Non-Authoritative Pending Review

**Status:** Accepted
**Date:** 2026-09-01

P1-57 may send P1-56 extracted attachment content to a route-specific AI parser only after P1-54 metadata allowlisting, P1-55 trusted-route verification/content validation and P1-56 bounded extraction have all succeeded. The email subject, body and each extracted attachment section must pass the approved privacy transform before AI interpretation. Attachment filenames, provider IDs, raw bytes and verification hashes are not included in the parser bundle.

The total pre-privacy interpretation bundle is limited to 120,000 characters and is never silently truncated. Oversize or privacy-transform failure returns manual review without invoking a parser. Customer interpretation may produce a ShipmentProposalSnapshot and supplier interpretation may produce a SupplierResponseExtraction, but P1-57 does not persist either interpretation, create a customer extraction-confirmation record, attach a supplier RFQ response or alter any RFQ lifecycle state. Applying interpreted attachment facts requires a separate controlled human-review boundary.

P1-57 interpretation is explicit per operator pull, not enabled merely by deploying the feature. The normal Outlook pull keeps attachment interpretation disabled. Only a pull request carrying `interpret_attachments=true` (the operator CLI `--interpret-attachments` flag) may inject the interpretation boundary for that bounded pull.

## DEC-149 — Attachment Interpretation Requires a Durable Human Review Before Apply

**Status:** Accepted
**Date:** 2026-09-01

P1-58 introduces a durable `AttachmentInterpretationReview` only after the P1-57 interpretation succeeds. Creating the review is not approval and has no downstream workflow authority. The review stores the privacy-safe interpreted candidate plus provider-neutral attachment verification evidence, including content profile, bounded size and SHA-256 source fingerprints. Provider attachment IDs and raw attachment bytes remain excluded.

A customer attachment review may be applied only by an authenticated operator. Apply creates a normal, still-unconfirmed `ShipmentExtractionProposal` linked back to the review; the existing extraction-confirmation and resume gates remain mandatory before operational processing. Trusted customer identity is fixed from the verified sender profile and cannot be replaced by the AI candidate during P1-58 review.

A supplier attachment review may be applied only if the exact Supplier RFQ snapshot captured at review creation is still unchanged. Apply validates optional operator corrections, creates the traceable `SupplierRFQResponse`, records attachment-aware inbound evidence and advances the RFQ lifecycle through the existing supplier response transition. If the RFQ changes before apply, the review remains pending and no response is created.

The review can instead be rejected with an authenticated operator identity and reason. Rejection creates no customer proposal, supplier response, mailbox write or outbound send. Review fingerprints and attachment hashes are durable audit evidence but are not exposed by operator list/detail payloads.

## DEC-150 — Attachment Review Apply Requires an Exact Field Preview

**Status:** Accepted
**Date:** 2026-09-01

P1-59 adds a read-only field-level preview between a pending P1-58 attachment review and its pilot apply mutation. The preview uses the same route-specific correction validators as apply, classifies customer safety fields and supplier commercial fields, identifies locked fields, shows normalized before/after values, and reports blockers/warnings without changing review, proposal, RFQ, response, mailbox or outbound state.

The preview returns a deterministic token bound to the review ID, durable source fingerprint, current review status, submitted corrections and normalized candidate. The authenticated pilot apply endpoint requires that exact token and recomputes the preview before mutation. A missing, stale or mismatched preview token fails closed. The token is not authentication and does not replace the named operator, pilot network or lifecycle checks.

## DEC-151 — Pending Attachment Reviews Use a Deterministic Read-Only Operational Queue

**Status:** Accepted
**Date:** 2026-09-01

P1-60 adds a read-only operational queue for pending attachment interpretation reviews. Queue priority is recomputed from current durable review/RFQ state on every read; priority labels and scores are not persisted and no AI model is used for ordering. Applied and rejected reviews are excluded.

Each pending review starts at score 10. Review age adds 5/10/20/30 points at 4/12/24/48 hours. The P1-59 baseline preview adds up to 30 points for a non-apply-ready blocker, 15 points per critical-attention field up to 45, and 5 points per warning up to 20. A missing or stale supplier RFQ snapshot adds 60 points; an RFQ that is no longer review-applicable adds 40. Customer required-delivery/cargo-ready dates and supplier quote-validity/vehicle-availability dates add bounded urgency points only when the source value is an exact `YYYY-MM-DD` date. Free-form dates are never guessed.

Scores are capped at 100 and map to `critical >= 70`, `high >= 45`, `normal >= 20`, otherwise `low`. Ordering is priority band, score descending, nearest known deadline, oldest review, then review ID. Queue output is privacy-minimal: it may expose review ID, route, RFQ ID, age, aggregate attention/blocker/warning counts, priority reason codes and relative deadline distance, but not subject, customer identity, candidate field values, corrections, preview tokens, source fingerprints, attachment hashes, provider IDs or raw/extracted attachment content.

## DEC-152 — Human Work May Be Unified for Prioritization Without Unifying Workflow Authority

**Status:** Accepted
**Date:** 2026-09-01

P1-61 introduces one read-only operational work queue across human-gated attachment review, customer extraction confirmation, supplier clarification follow-up and quote approval. The queue may also surface a `clarification_required` Supplier RFQ that has no active follow-up as a high-urgency operational gap. It does not replace or merge the underlying attachment-review, extraction-confirmation, Supplier RFQ or quote-approval state machines.

Only work requiring a current human action is eligible. Pending attachment reviews, proposed customer extractions, supplier follow-up drafts/approved follow-ups, clarification gaps and pending quote approvals may appear. Resolved decisions and supplier follow-ups already awaiting an external response are excluded. Priority is recomputed on every read from durable current state; it is not persisted and does not call AI.

Cross-work priority uses a common human-action baseline plus bounded current-state signals: age, safety/commercial attention, exact ISO `YYYY-MM-DD` deadlines and lifecycle consistency. Free-form dates are never guessed. Existing P1-60 attachment-review scoring remains backward-compatible and is incorporated as one source signal.

The unified queue is privacy-minimal. It may expose internal resource IDs, work type, route/status, next-action code, age, aggregate warning/blocker/attention counts, priority reason codes and relative deadline distance. It must not expose customer/supplier identity, email addresses, message subject/body, interpreted candidate values, quote price/cost/currency, supplier clarification text, preview tokens, attachment/source hashes, provider IDs or raw/extracted content.

P1-61 also treats inconsistent durable state as blocked work rather than an action accelerator. A supplier follow-up with prior send evidence while still `draft`/`approved`, or multiple active follow-ups for the same RFQ, is routed to inspection instead of approval/send. A pending quote approval with no unique QuoteCase, stale case approval state, or prior customer-quote sent evidence is likewise routed to inspection rather than approval/rejection acceleration.

## DEC-153 — Operational Work Detail Provides Recovery Guidance Without Action Authority

**Status:** Accepted
**Date:** 2026-09-01

P1-62 adds an authenticated read-only detail view for a current P1-61 operational work item. Detail is resolved from the current durable repositories on every read; if the work item is no longer active, the detail request fails closed as not found rather than presenting stale recovery guidance.

The detail may expose internal work/resource IDs, current safe status flags, blocker/priority reason codes, unknown field names/counts, lifecycle consistency booleans and structured operator-command argv. It must not expose customer/supplier identities, email addresses, subject/body content, interpreted candidate values, commercial amounts/currency, supplier clarification text, preview tokens, attachment/source hashes or provider identifiers.

Recovery commands reference only existing controlled operator surfaces. They are navigation/advice, not authorization. A later confirm/approve/send/apply/reject/resume call must still satisfy the authoritative workflow's authentication, preview-token, stale-state, approval, provenance and send guards at execution time.

## DEC-154 — Operational Work Assignment Coordinates Operators Without Granting Workflow Authority

**Status:** Accepted
**Date:** 2026-09-01

P1-63 adds durable assignment and acknowledgement metadata to current P1-61/P1-62 operational work items. Assignment exists only to reduce duplicate human effort. It does not confirm customer extraction, approve/reject quotes, approve/send supplier follow-ups, apply/reject attachment reviews, resume workflows, write mailboxes or send outbound mail.

`assign-to-me` derives the assignee exclusively from the authenticated pilot operator identity. Claim is serialized through the shared SQLite transaction boundary; for the same current work state only one named operator may hold an active assignment. Repeating assign/acknowledge by the same operator is idempotent. Another operator receives a lifecycle conflict until the current assignee releases the item or the work state changes.

Assignments are bound to a provider-neutral safe fingerprint of the current work state (work/resource type, status, next-action, created time and aggregate blocker/warning/attention counts). The fingerprint is stored only as internal coordination evidence and is never returned by API/CLI. If the work state changes, the old assignment is treated as stale and does not carry ownership into the new state; a fresh assignment generation may be created.

Queue priority and underlying workflow authority are unchanged by assignment. Active queue/detail output may show assignment status, named operator, assignment/acknowledgement timestamps and generation. Released or stale assignments are not active authority; event history remains durable under normal pilot retention.

## DEC-155 — Operational Work Assignment Uses a Bounded Lease and Explicit Takeover

**Status:** Accepted
**Date:** 2026-09-01

P1-64 bounds every new operational work assignment with a 30-minute coordination lease. Assignment and lease are advisory operator-coordination metadata only; they do not grant, extend or replace confirm, approve, send, apply, reject, resume, provenance or lifecycle authority.

A first acknowledgement refreshes the lease once because it marks the operator actively beginning review. Later lease extension is explicit through `work renew` and is allowed only to the authenticated current assignee while the current work-state fingerprint still matches and the lease is not expired. There is no background heartbeat or silent renewal.

After expiry, normal assign, acknowledge and renew fail closed. Recovery requires explicit `work takeover`, which is permitted only while the work item still exists, the prior assignment matches the same current work state and the lease is expired. Takeover starts a new assignment generation and is serialized under the same SQLite transaction boundary so concurrent takeover attempts have exactly one winner.

Legacy active P1-63 assignment records that do not contain a lease expiry are treated as expired rather than indefinitely owned. Released legacy records remain durable audit history. Queue/detail may expose safe lease status, expiry/remaining-time metadata and takeover availability, but never the internal work-state fingerprint. Lease state does not change work priority.

## DEC-156 — My Work Is Authenticated Self-Scoping and Shift Handoff Releases Ownership

**Status:** Accepted
**Date:** 2026-09-01

P1-65 adds an authenticated `My Work` view over current operational assignments. The server derives the operator exclusively from the pilot authentication context; clients cannot request another operator's personal queue. Only current work items whose assignment is lease-active and in `assigned` or `acknowledged` state for that operator appear. Expired, released, stale-state and other-operator assignments are excluded.

My Work reuses the privacy-minimal P1-61 queue surface and does not expose additional customer, supplier, message, commercial, attachment or fingerprint data. Items are ordered by remaining lease time first and then existing priority; assignments with five minutes or less remaining are marked `expiring_soon`. This lease attention does not modify the underlying priority score or action authority.

P1-65 also adds explicit shift handoff. Handoff is permitted only to the authenticated current assignee while the same work state and lease remain active. It atomically records the assignment as released with system-controlled `release_reason=shift_handoff`. It does not accept a target operator or free-form handoff note and does not auto-assign a successor. The next operator must refresh the queue and use normal `work assign`, creating a fresh assignment generation.

## DEC-157 — Shift Summary Reads Current Work and Append-Only Handoff History Without Creating New Authority

**Status:** Accepted
**Date:** 2026-09-01

P1-66 adds an authenticated, read-only shift summary for one pilot operator. The summary combines the operator's current lease-active P1-65 My Work view, lease-expiry attention, that operator's recent `shift_handoff` assignment events, and current critical unassigned work from the unified operational queue. It does not assign, renew, hand off, take over, confirm, approve, send, apply, reject or resume anything.

Recent handoffs are read from the existing append-only operational assignment event history rather than inferred from the current assignment snapshot. The read window is fixed at 12 hours and capped at 20 handoff records. Successor claims may replace the current assignment state but must not erase the prior handoff readout. Raw event payloads and internal work-state fingerprints are never returned.

The summary is scoped to the authenticated pilot operator. It may expose safe work IDs/types, current priority/routing metadata, lease attention, handoff time/generation and a coarse current disposition (`available_unassigned`, `claimed`, `expired_assignment`, `state_changed`, or `resolved_or_inactive`). It must not expose party identity, email/message content, commercial amounts/currency, provider identifiers, attachment/source hashes or internal fingerprints. Existing workflow guards remain authoritative.

## DEC-158 — Shift Close Readiness Is a Read-Only Fail-Closed Coordination Gate

**Status:** Accepted
**Date:** 2026-09-02

P1-67 adds an authenticated shift-close readiness readout. It does not close a shift, release or assign work, record a close event, or grant workflow authority. `ready_to_close=true` is descriptive coordination state only and is returned only when the authenticated operator has no current active assignment, no same-state expired assignment, no incomplete recent handoff, and no current critical unassigned work.

Active assignments block close readiness even when their lease is healthy. Expiring-soon active leases remain a separate warning so the operator can distinguish ordinary unfinished work from urgent lease attention. Expired same-state assignments are checked outside My Work because P1-65 intentionally excludes expired ownership; an expired assignment must not disappear from shift-close accounting merely because it is no longer lease-active.

Recent handoffs reuse the bounded P1-66 handoff history. `claimed` and `resolved_or_inactive` are complete dispositions. `available_unassigned`, `expired_assignment`, and `state_changed` fail closed as incomplete because receiving coverage is not currently proven. Critical unassigned work independently blocks readiness even when it did not originate from the closing operator.

The readout may return privacy-minimal work IDs/types, priority/routing metadata, lease state and handoff disposition plus descriptive existing CLI command names for remediation. It must never execute those commands, expose internal work-state fingerprints or raw assignment events, or include party identity, message content, commercial values, provider identifiers or attachment/source hashes.

## DEC-159 — Shift Close Attestation Records State-Bound Audit Evidence Without Creating Authority

**Status:** Accepted
**Date:** 2026-09-02

P1-68 adds an explicit authenticated shift-close attestation that may create durable evidence only when P1-67 recomputes the current state as `ready_to_close=true` inside the same atomic SQLite transaction that records the receipt. A prior readiness GET is never sufficient evidence for attestation, and a blocked current state fails closed without writing a receipt.

Each receipt is bound to a server-side SHA-256 fingerprint of the authenticated operator scope, privacy-safe current unified queue/assignment coordination state, recent handoff disposition and readiness checks. The fingerprint is internal and never returned by API/CLI. Same operator plus the exact same close state is idempotent and resolves to one durable receipt; a changed close state requires a fresh receipt.

Receipt history is authenticated-self-scoped and bounded for operator readout. A receipt is reported as `current` only while the current state still recomputes ready and matches its internal fingerprint; otherwise it remains immutable historical evidence marked `stale`. A receipt never authorizes assignment, confirmation, approval, send, apply, reject, resume or any future shift close.

P1-68 also tightens P1-67 critical coverage: critical work is covered only by a lease-active `assigned` or `acknowledged` assignment. Unassigned, stale or expired critical ownership is uncovered and blocks close readiness, including when the expired assignment belongs to another operator.

The state binding also includes the latest non-receipt pilot event high-water mark when SQLite durability is available. Shift-close receipt events themselves are excluded from that watermark so writing a receipt does not invalidate itself. Any later operational persistence event advances the watermark monotonically, preventing an old receipt from becoming current again merely because visible queue state later returns to a previous shape.

## DEC-160 — Incoming Shift Reconciliation Uses the Latest Global Close Receipt Without Reopening Authority

**Status:** Accepted
**Date:** 2026-09-02

P1-69 adds an authenticated, read-only incoming-shift reconciliation view. The view anchors to the latest durable P1-68 shift-close receipt across the pilot operation rather than only receipts created by the incoming operator. The closing operator identity remains internal and is never returned. A prior receipt is historical evidence only; reconciliation never converts it into assignment, workflow or shift-open authority.

The reconciliation compares the prior close evidence with current operational state, surfaces current critical work that lacks lease-active assigned/acknowledged coverage, and evaluates recent shift handoffs across all operators without exposing who released or owns the work. Recent incomplete handoffs remain limited to the existing 12-hour/20-item coordination boundary.

Changes since close are summarized from SQLite event metadata after the receipt's non-receipt high-water mark. Receipt events are excluded. The read path must never decode or return historical event payloads, entity IDs or raw internal entity types. Public change categories are coarse operational classes such as work coordination, customer extraction, supplier operations, customer quote and attachment review. If no prior receipt or no trustworthy change watermark is available, reconciliation fails safe into review-required rather than assuming continuity.

## DEC-161 — Incoming Shift Acceptance Is Explicit, State-Bound Evidence and Never Opening Authority

**Status:** Accepted
**Date:** 2026-09-02

P1-70 adds an explicit authenticated incoming-shift acceptance receipt. Acceptance may be recorded only when P1-69 is recomputed inside the same atomic SQLite transaction and returns `reconciliation_status=clear` with `review_required=false`. A prior reconciliation GET is advisory only; if continuity changes before POST, acceptance fails closed without evidence.

Each acceptance is scoped to the authenticated incoming operator and bound to a server-side SHA-256 projection of the current privacy-safe reconciliation state, including the latest global close receipt, change summary, current queue coverage and incomplete handoff state. The internal fingerprint and `accepted_by` identity are never returned. Same operator plus exact same reconciliation state is idempotent; another operator may record their own independent acceptance without transferring ownership or opening a global shift state.

Shift-close and shift-open acceptance receipts are both evidence-only pilot events and are excluded from P1-68/P1-69 operational state high-water/change accounting. Therefore writing evidence never invalidates itself. Any later real operational persistence event makes the old acceptance stale through fresh reconciliation, and a later clean cycle requires fresh close evidence plus a new acceptance rather than resurrecting an old receipt.

## DEC-162 — Shift Continuity Ledger Separates Historical Completion From Evidence Freshness

**Status:** Accepted
**Date:** 2026-09-02

P1-71 adds an authenticated organization-level, read-only shift continuity ledger that pairs retained P1-68 close evidence with P1-70 incoming acceptance evidence without exposing closing or accepting operator identity. The ledger is an audit projection only; it does not open or close a shift, claim or transfer work, or grant workflow authority.

A continuity cycle is not defined by raw receipt count. Multiple close attestations produced against the same durable operational high-water state before any acceptance are duplicate evidence for one cycle and are grouped together. Once a cycle has an acceptance, a later close attestation starts a new cycle even when no operational work changed in between, preserving quiet-shift boundaries.

Each cycle reports `completion_status` separately from `evidence_freshness`. `complete` means at least one temporally valid acceptance was recorded for that close cycle. `open` means the latest retained cycle still awaits acceptance. `gap` means an older close cycle was superseded without any valid acceptance. Freshness is `current`, `stale` or `historical`; later ordinary operational activity may make otherwise complete evidence stale, but staleness alone must never be reclassified as a continuity gap.

The organization ledger may expose opaque close receipt anchors, bounded timestamps, duplicate close counts, acceptance counts and audit status codes. It must not expose `attested_by`, `accepted_by`, acceptance receipt IDs, internal state-event watermarks, fingerprints, raw event payloads, party identity, message content or commercial values. Retention-boundary acceptances whose source close has already expired may be counted as unmatched metadata but are not automatically treated as corruption.

## DEC-163 — Primary Suppliers Are Protected as a Parallel Group and Silence Is Never Capacity Failure

**Status:** Accepted
**Date:** 2026-09-02

P1-72 replaces timeout-driven supplier fallback assumptions with the freight-operations behavior confirmed by the agency. For a road RFQ, every eligible selected primary supplier is prepared as the first dispatch group in parallel. A supplier whose configured role is `backup` is secondary; a selected `primary` or selected `specialist` is treated as primary for this transition model. This is intentionally compatible with a future lane/service-specific tier model rather than claiming that supplier priority must be globally fixed forever.

RFQ send and supplier acknowledgement are distinct facts. A sent RFQ with no confirmed acknowledgement remains unconfirmed. After 30 minutes of silence the policy calls for a reminder, not automatic fallback. If silence continues after that reminder, the required escalation is human telephone/WhatsApp contact and, when necessary, manager/owner escalation. Silence, non-answer, or an unread email must never be converted into `no_capacity`.

A supplier message that explicitly confirms receipt, visibility, or active work without giving a commercial result is `acknowledged` evidence, not a quote. Acknowledgement may come from email or authenticated manual phone/WhatsApp evidence. The normal road grace period is 120 minutes from confirmed acknowledgement; only after that period is another reminder due. Acknowledgement leaves the RFQ awaiting a real commercial response.

Secondary suppliers remain fail-closed while any primary supplier is silent, acknowledged/working, or otherwise unresolved. Secondary release is permitted when every primary is resolved and each is either explicitly `no_capacity`/`declined` or has provided a quote that deterministically cannot meet an explicit customer-required delivery date. Missing/uncertain transit evidence never counts as delivery incompatibility and must be clarified instead. Commercial fallback for high prices is separately permitted only after every primary has a terminal result, at least one primary quote exists, and an authenticated operator records that primary price negotiation has been exhausted. Customer urgency never bypasses the primary group by itself.

Customer target price is internal commercial information. When a customer target exists, supplier negotiation must use an agency buy target derived after protecting the agency's expected profit; the customer's raw target must not be disclosed or persisted in secondary-release evidence. The policy also records a five-minute proactive customer-deadline update lead time. P1-72 does not invent a structured quote deadline from free text; deadline extraction and proactive customer status sending require a separately validated structured intake step.

## DEC-164 — Timed Supplier and Customer Automation Runs Only Inside Agency Business Hours

**Status:** Accepted
**Date:** 2026-09-02

P1-73 adds controlled timed outbound automation for supplier reminders and proactive customer quote-deadline updates. Supplier reminders are automatic by default but independently disableable. The first silence reminder is due after 30 business minutes with no acknowledgement or commercial response. An acknowledgement/working response suppresses that timer and starts a 120-business-minute grace period; at most one acknowledgement reminder is sent. After an automatic reminder, further silence becomes human telephone/WhatsApp escalation rather than repeated email.

Customer quote-response deadlines are stored only from explicit timing evidence such as a stated clock time or bounded relative duration. Urgency alone, delivery timing and supplier transit duration never create a customer quote deadline. When no usable supplier price exists, the default proactive customer update is sent once, five minutes before the explicit quote deadline. If that deadline falls after working hours, the update moves to five minutes before the same business-day close when possible; no second after-hours update is sent.

The default agency calendar is Europe/Istanbul, Monday-Friday, 09:00-18:30. Supplier reminder and acknowledgement grace periods count business minutes only; evenings and weekends pause the clock. Automatic supplier/customer mail and phone/WhatsApp escalation work do not run outside the business window. Inbound email may still be received and persisted outside hours. A supplier response received while the timer is paused is re-evaluated before the next action, preventing stale reminders.

MINAI provider delivery for approved initial supplier RFQs and controlled supplier follow-ups is blocked outside business hours before any provider call. Existing human approval authority is unchanged: P1-73 does not grant automatic initial RFQ send authority. An approved draft remains pending until business hours and may then be sent through the existing controlled action. Pre-P1-73 workflows are not retroactively activated for timed automatic reminders.

Each scheduled automatic send uses durable single-action reservation before provider delivery. Concurrent scheduler ticks may reserve at most one send. State is recomputed immediately before delivery; late supplier/customer progress cancels stale sends. Provider failure is not blindly retried and instead becomes privacy-minimal human attention. Scheduled-action records do not persist customer or supplier email addresses.
## DEC-165 — Supplier Communication Calendar Is Fixed and Customer Deadline Communication Is Independent

**Status:** Accepted
**Date:** 2026-09-02

P1-74 narrows the P1-73 business-hours concept to supplier communication only. The Turkey supplier communication calendar is a system operational assumption, not an agency preference: Europe/Istanbul, Monday-Friday, 09:00-18:30. These hours are intentionally not part of configurable supplier dispatch policy and must not be exposed as a Guide Editor setting.

Supplier timers, automatic reminders, phone/WhatsApp escalation work, approved initial supplier RFQ provider sends and controlled supplier follow-up provider sends use this fixed supplier calendar. Turkish official public holidays also close supplier communication. Full holidays close the entire day; statutory half-day eves close the supplier window at 13:00.

Customer quote-deadline communication is separate. If a customer explicitly requests a quote by 20:00, the default five-minute proactive update is due at 19:55 even though supplier communication has ended. Supplier working hours must never pull that customer update back to 18:25 or suppress it solely because the supplier window is closed.

Religious holiday dates are maintained as verified year-specific calendar data while fixed national holidays remain deterministic. The initial verified religious-holiday coverage is 2026-2028. If supplier automation reaches an unverified calendar year, it fails closed instead of assuming the day is open. Future import workflows may select a supplier/agent country and regional calendar, but P1-74 does not implement foreign calendars yet.


## DEC-166 — A MINA Job Is the Durable Identity of One Logistics Job, Not One Quote

**Status:** Accepted
**Date:** 2026-09-02

P1-75 introduces a durable MINA job/case identity. A code such as `MINA2026/1` is allocated only when a customer inquiry is human-confirmed as a genuine operational job. Unconfirmed extraction proposals, spam and rejected intake must not consume a MINA sequence number. Numbering is yearly in Europe/Istanbul and concurrent confirmations must reserve unique sequence numbers atomically.

The MINA identity survives the commercial quote lifecycle. Supplier RFQ workflow, quote case, customer quote revisions and later operational stages remain attached to the same job. A revised customer quote is Rev.1/Rev.2 inside the same MINA job rather than a new MINA code. The intended lifecycle extends through accepted, operations, in-transit and delivered; delivery is the normal operational completion point. Lost/rejected and cancelled are explicit terminal alternatives.
MINA job state and timeline are durable operational records and are not subject to the pilot store's ordinary 30-day state purge. This exception does not remove retention controls from raw inbound mail, supplier/customer message bodies or ordinary pilot state. Timeline records should carry operational event metadata, references and authenticated actor evidence without becoming an unrestricted archive of message content.

Agency-level automation policy remains the default, but a MINA job may disable supplier reminders and/or customer deadline updates for that job only. A job override may reduce automation authority but must not re-enable an automation disabled globally. In P1-75 the supplier reminder override is job-wide; supplier-specific persistent override settings are intentionally deferred.

An authenticated operator may preview and trigger an individual supplier reminder early from the MINA job. This does not bypass supplier communication hours or holiday controls. The early send consumes the same durable reminder action that the scheduler would later use, so the scheduled 30/120-minute reminder cannot be duplicated. Provider delivery is rechecked against current supplier state immediately before send and operator identity is retained as evidence.

P1-75 provides backend job list/detail and controlled action surfaces for the future MINA main screen. It does not implement the P1-76 graphical job dashboard or Guide Editor settings. Visual MINA codes retain the slash format while API resource routing uses the opaque job ID.

## DEC-167 — MINA Jobs Are the Default Operations Workspace While UI Authority Remains API-Controlled

**Status:** Accepted
**Date:** 2026-09-02

P1-76 makes the MINA job list the default development workspace. Operators can search/filter durable jobs, open one job, review its current lifecycle stage, customer/route summary, supplier RFQ state, quote/revision summary, automation state and chronological operational timeline.

The job-detail UX exposes only deliberate human controls already authorized by P1-75: job-level automation disable overrides, supplier reminder preview/early-send, customer acceptance, operations/in-transit/delivered progression, and explicit lost/cancelled closure. Quote preparation/send progression remains system-driven rather than a manual stage toggle.
Streamlit remains a development-only UI and is not promoted to controlled-pilot authority by P1-76. It does not embed pilot bearer credentials or bypass authentication. Real mutations remain enforced by the authenticated API and existing lifecycle guards. A future pilot-approved browser shell must add its own authenticated session/binding controls before this UI can become the live operator surface.

Timeline rendering is deliberately curated rather than a raw metadata dump. It may show operational event meaning, time, actor and bounded safe summaries, but not internal fingerprints, provider credentials or protected commercial-release evidence. MINA timestamps are rendered in Europe/Istanbul regardless of workstation timezone.

## DEC-168 — MINA Lifecycle v2 Extends One Durable Job Through Documented Operational Closure

**Status:** Accepted
**Date:** 2026-09-04

P2-01 introduces versioned MINA job lifecycle semantics so the Freight OS can grow without rewriting or invalidating persisted pilot jobs. Records created before P2-01 remain lifecycle v1 by default and retain the P1-75 behavior in which `delivered` is terminal. Newly created jobs use lifecycle v2. No bulk migration of legacy jobs is implied by this decision.

Lifecycle v2 distinguishes `price_request` from `approved_job`. A price request follows supplier pricing and the customer quote lifecycle before operation. An approved job still requires supplier pricing but may move from `pricing` directly to `operation_opened`; it must not be forced through customer quote states. Email-confirmed jobs retain extraction-proposal identity, while phone, WhatsApp, portal, face-to-face and other manual intake may create a job with a separate idempotent manual intake identity rather than fabricating an email proposal.

The v2 operational lifecycle is deliberately explicit: `operation_opened` → `supplier_confirmation_pending` → `vehicle_details_pending` → `vehicle_assigned` → `pre_loading_check` → `ready_for_loading` → `loaded` → `in_transit` → `delivery` → `delivered` → `pod_cmr_pending` → `closing_review` → `completed`. In lifecycle v2, `delivered` is not terminal. Normal completion requires POD/CMR follow-up and closing review; only `completed`, `lost` and `cancelled` close a v2 job.

A MINA job may also retain durable `sales_owner` and `operations_owner` responsibility independently from temporary operational-work assignment leases. Owner changes require authenticated actor evidence and append-only timeline events containing the prior and new bounded owner values. The backend remains authoritative for allowed next stages, and UI controls must derive or filter actions using that backend transition authority.

## DEC-169 — Supplier Price Acquisition Is Source-Neutral and Fixed Rates Materialize Into Job Offers

**Status:** Accepted
**Date:** 2026-09-04

P2-02 broadens supplier pricing beyond RFQ responses without weakening the existing RFQ lifecycle. A reusable `SupplierFixedRate` represents an agreed price with explicit lane, optional city/region/service/equipment scope, commercial terms, validity dates and evidence source. A `SupplierPriceOffer` represents a price candidate for one durable MINA job and may originate from RFQ/email, phone, WhatsApp, portal, API, manual entry or an applicable fixed rate.

Using a fixed rate does not mutate or consume the reusable agreement. The system deterministically verifies the rate against the job shipment and validity window, then materializes one job-specific price offer that retains the fixed-rate identity as provenance. Route, date, service or equipment uncertainty fails closed rather than broadening the agreement. Exact stored region labels may match explicit shipment area fields; semantic region inference (for example mapping a postcode to DACH/Bavaria) is intentionally deferred until supplier/customer master-data provides an authoritative geography model. Fixed-rate commercial terms are immutable evidence; an agreement may be explicitly activated/deactivated, while changed price/scope/validity requires a new rate record.

RFQ-derived, direct and fixed-rate offers may be projected into the same multi-criteria supplier quote comparison engine. The selected `SupplierQuote` can retain the normalized price-offer ID, source type and source reference so later quote approval and audit do not lose how the supplier cost was obtained. Existing RFQ quote selection remains backward compatible.

Fixed rates and job-specific supplier price offers are durable commercial/operational evidence and survive the ordinary pilot state retention purge. Client-generated entry identities make fixed-rate creation and direct price entry idempotent, while a given fixed rate may materialize at most once for the same MINA job. P2-02 does not introduce supplier master-data, geographic-strength learning or automatic region inference; those remain P2-03 scope.

## DEC-170 — Customer and Supplier Master Data Become Durable Domain Records Without Immediate Pilot Cutover

**Status:** Accepted
**Date:** 2026-09-04

P2-03 introduces durable `CustomerMasterProfile` and `SupplierMasterProfile` records as the future first-class identity and capability layer for the Freight OS. Customer master data carries stable identity, aliases, trusted sender evidence, contact/authority roles, responsible sales owner, customer pricing policy, operational defaults and notes. Supplier master data carries stable identity, contacts, service/equipment capabilities, commercial performance inputs and explicit geography capabilities with business-strength labels (`main_market`, `strong`, `works`, `limited`).

The existing `customer_memory.json` and `supplier_capabilities.json` datasets are not removed or silently rewritten by P2-03. They remain the current pilot-compatible operational datasets and may be imported through an explicit, authenticated, idempotent legacy bootstrap into the durable master repository. Compatibility projections back to the current customer-memory and supplier-capability contracts must remain valid before any runtime cutover is authorized.

Master profile names are stable identifiers in P2-03 and cannot be silently renamed. Future rename/merge requires a separately controlled identity operation because existing jobs, quotes, emails and audit evidence may refer to the prior name. Master records and their identity indexes are durable evidence and survive ordinary pilot retention purges.

## DEC-171 — Automation Authority Resolves Agency → Customer → Job With Explicit Human-Approval Mode

**Status:** Accepted
**Date:** 2026-09-04

P2-04 introduces a durable automation-policy hierarchy for external operational actions. The supported initial actions are supplier reminders and proactive customer deadline updates. Each action may resolve to `manual`, `approval_required`, or `automatic`. Resolution is deterministic and uses the most specific applicable authority: explicit job mode first, then legacy job-level disable as a compatibility fail-safe, then active customer master policy, then durable agency policy, and finally the pre-P2-04 dispatch-policy boolean as legacy fallback.

`approval_required` is distinct from both manual and automatic execution. The automation planner must create an explicit human-review state and the automatic scheduler must not send the external message. P2-04 establishes policy authority, planner states, scheduler enforcement and operational-work queue visibility; a generalized one-click outbound approval/execution workflow remains a separate controlled implementation concern rather than being fabricated inside the scheduler.

Persisted jobs and older API clients remain backward compatible. Existing `disable_supplier_reminders` and `disable_customer_deadline_updates` fields remain supported and act as job-level manual fail-safes when no modern explicit mode exists. Partial policy updates must preserve fields omitted by older or narrower clients. A durable agency policy containing no explicit mode for an action falls back to the existing supplier dispatch policy instead of silently changing current pilot behavior.

## DEC-172 — Operation Execution Evidence and Exceptions Are Separate From the MINA Lifecycle State

**Status:** Accepted
**Date:** 2026-09-04

P2-05 adds a durable operation-execution layer to lifecycle-v2 MINA jobs. The MINA stage remains the coarse workflow authority, while `OperationExecutionSnapshot` stores the current structured operational evidence such as supplier confirmation, vehicle/driver assignment, loading, location/ETA, delivery and POD/CMR receipt. This avoids turning every operational fact into a lifecycle state.

Operational exceptions are separate durable records layered over the current job stage. An in-transit job may therefore simultaneously carry a deviation, delivery risk or actual delay without transitioning into a synthetic `delay` stage. Exception impact is explicit evidence and must not be inferred solely from a date-only promised-delivery field. `deviation` means the customer promise is not currently threatened, `delivery_risk` means the promise may be missed, and `actual_delay` means a promised delivery will or has been missed.

Lifecycle-v2 API transitions may require structured execution evidence. Vehicle assignment requires durable plate, driver and assignment time; loaded requires loading-time evidence; delivered requires delivery-time evidence; closing review requires delivery plus POD or CMR receipt; and normal completion is blocked while any operation exception remains open. Lifecycle-v1 records retain their pre-P2-05 transition semantics. Lost/cancelled jobs may still resolve a pre-existing exception with explicit resolution evidence, but closed jobs cannot receive new execution facts or new exceptions.


## DEC-173 — Learned Facts Require Explicit Evidence and Human Confirmation Before Runtime Authority

**Status:** Accepted
**Date:** 2026-09-04

P2-06 introduces durable `LearningFact` records for customer, supplier, route and operation knowledge. A fact stores one bounded subject/key/value assertion together with confidence, source type and one or more bounded evidence references. Confidence is advisory only: a `proposed` fact is never runtime-authoritative, even at very high confidence. Runtime authority begins only after explicit human confirmation with actor, time and review note.

Learning history is append-oriented. A changed fact must not silently overwrite a previously confirmed value. A replacement is created as a new proposed fact with an explicit `supersedes_fact_id`; confirmation atomically supersedes the prior confirmed fact and makes the replacement the single active runtime authority for that subject/key. Rejected and superseded facts remain durable historical evidence.

P2-06 establishes fact authority, evidence, review lifecycle, APIs and UI review. It does not yet authorize autonomous extraction from historical inboxes, automatic master-data mutation, or automatic use of proposed facts in pricing, supplier selection or external communication. Those require separate evidence-backed integrations.

## DEC-174 — Reporting Is a Read Model Over Durable Freight OS Authority, Not a Second Source of Truth

**Status:** Accepted
**Date:** 2026-09-04

P2-07 introduces reporting read models for general overview, sales personnel, operations personnel, customers, suppliers, routes/countries, financial performance, MINAI performance, exceptions/delays and data-quality coverage. These reports are computed from existing durable authorities such as MINA jobs/timeline, QuoteCase, supplier RFQ/price evidence, operation execution/exceptions, master data and reviewed LearningFact records. P2-07 does not introduce a second mutable reporting database or allow the UI to recompute business authority independently.

The default period filter is a deterministic cohort based on the MINA job `opened_at` date in `Europe/Istanbul`, inclusive of the requested start/end dates. Historical milestone metrics such as quote sent, accepted and operation opened must use durable timeline evidence so later lifecycle stages do not erase earlier funnel history. Current workload metrics may use the current durable stage.

Financial reporting is evidence-covered rather than gap-filled. Customer value, supplier cost and gross profit may be reported only when a durable CustomerQuote provides the required evidence. Missing price evidence remains explicitly uncovered and must never be coerced to zero. Monetary totals are grouped by currency and must not be summed across currencies without a future explicit FX authority.

P2-07 exposes read-only `/reports` and `/reports/{section}` API surfaces plus a development `Raporlar` workspace. The UI consumes backend-derived KPIs and must not independently calculate profit, conversion or SLA authority.

P2-07 MINAI learning metrics state their own activity basis as `learning_fact_created_at_istanbul` when date filters are supplied; they are not silently presented as job-cohort events. The outbound automation-share metric is explicitly limited to tracked provider/send evidence for initial supplier RFQs, supplier follow-ups and customer quote sends. Other automated action types must not be implied by that percentage until equivalent durable provider evidence is included.

## DEC-175 — Approval-Required Outbound Actions Need Explicit Operator Decision and Fresh Pre-Send Authority

**Status:** Accepted
**Date:** 2026-09-04

P2-08 turns the P2-04 `approval_required` policy state into an executable human-approval boundary for supplier reminders and proactive customer quote-deadline updates. Preview is read-only: it renders the message from current authoritative state but does not reserve an action, persist message content or call a provider.

Approval and rejection require the authenticated operator identity. Approval reserves the same durable automation action key used by the scheduler, marks the trigger as `operator_approved`, and then immediately re-evaluates the current workflow, recipient-relevant state and effective automation policy before any provider call. A prior preview or click is never sufficient authority if the underlying state has changed.

Rejection records durable no-send evidence by consuming the action key as a cancelled action with `operator_rejected`; the same due state must not immediately reappear as another approval request. Rejection requires a bounded reason. Approval-provider failure is durable attention and must not be blindly retried.

The existing operator-early supplier reminder path remains available for manual/ordinary early-send use, but when the effective policy is `approval_required` the API must reject that path so it cannot bypass the explicit approval record. P2-08 does not promote Streamlit to a pilot-approved browser surface; the development UI only exposes the controlled preview/approve/reject API flow.

## DEC-176 — Pilot Browser Access Uses Server-Side Sessions Without Exposing Pilot Bearer Tokens

**Status:** Accepted
**Date:** 2026-09-04

P2-09 introduces an explicitly enabled FastAPI web operator shell for pilot use. The existing bearer-token pilot interface remains the authority for CLI/integration access, while browser users authenticate with email and password and receive an opaque server-side session. The browser must never receive, persist or reconstruct a pilot bearer token.

Web-shell passwords are configured outside the repository as bounded scrypt hashes. Plaintext passwords are invalid configuration. Pilot web access requires HTTPS even on loopback so the session cookie can remain `Secure`, `HttpOnly` and `SameSite=Strict`. Sessions carry an authenticated operator identity, absolute expiry, idle expiry and CSRF token; they are intentionally process-local and disappear on restart, which fails closed rather than preserving stale browser authority.

A browser session may access only API routes already admitted by the controlled pilot allowlist. Unsafe browser-session methods require a matching CSRF header before request-model or business processing. An explicit `Authorization` header takes precedence over browser-session authentication so existing bearer clients remain deterministic and do not silently fall back to cookies after a bad token.

The first P2-09 shell exposes MINA Jobs, bounded job detail, P2-08 supplier/customer approval execution and reporting. It remains a presentation shell over backend read models and mutation APIs; business rules, stage authority, automation authority and send safety stay server-side. Streamlit remains available as a development/debug workspace and is not the pilot browser authority.

## DEC-177 — The Pilot Home Screen Is a Backend-Authoritative Three-to-Five-Day Operations Calendar

**Status:** Accepted
**Date:** 2026-09-04

P2-10 changes the authenticated pilot shell's default landing page from the flat MINA job list to an operations dashboard. The dashboard presents a three-to-five-day Europe/Istanbul calendar built by the backend from durable MINA and operation-execution evidence. The first calendar evidence types are customer quote deadline, exact cargo-ready date, exact required-delivery date, loading appointment, current ETA and delivery appointment.

Date authority is fail-closed. Exact ISO dates and timezone-aware timestamps may be placed on the calendar; vague strings such as `next Friday` remain visible as unscheduled work rather than being interpreted by the browser or silently guessed by the backend. Closed MINA jobs are excluded from active workload counts.

Open `delivery_risk` and `actual_delay` operation exceptions remain separate authority from the calendar and are surfaced in a dedicated attention area. Overdue customer quote deadlines and overdue required-delivery dates may also create attention without fabricating a new lifecycle state. The existing MINA Jobs list remains available for search/detail navigation and the reporting workspace remains separate.

## DEC-178 — Pilot Operator Work Queue Reuses Durable Coordination Authority and Starts With Self-Claim

**Status:** Accepted
**Date:** 2026-09-04

P2-11 exposes the existing unified operational work queue and durable work-assignment authority in the authenticated pilot web shell. The browser does not create a second task system, recompute priority, or infer ownership. It reads the backend queue and authenticated operator's my-work view, then calls the existing controlled assign, acknowledge, renew, takeover and release APIs.

The first pilot browser assignment model is self-claim. An authenticated operator may claim unassigned work for themselves and may take over an expired assignment through the existing lease guard. P2-11 does not let one ordinary operator type an arbitrary name and assign work to another person. Directed person-to-person assignment requires a future authoritative operator directory plus an explicit permission model so identity and assignment authority cannot be fabricated in the browser.

The work-queue workspace provides bounded coordination views such as all open work, my assigned work, approval/confirmation work and unassigned critical work. These are presentation filters over the backend-authoritative item fields and ordering; they do not alter workflow state or priority authority.
