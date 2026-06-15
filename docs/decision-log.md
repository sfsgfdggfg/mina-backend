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
