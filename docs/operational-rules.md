# MINAI Freight OS

# Operational Rules v1

## RULE-001

Varsayılan araç tipi Tenteli olacaktır.

## RULE-002

ADR yükler hiçbir zaman varsayılmaz.

Müşteri açıkça belirtmelidir.

## RULE-003

Road Freight fiyatlandırmasında ölçüler ağırlıktan daha önemlidir.

## RULE-004

Özel ekipman gereksinimi belirtilmedikçe yok kabul edilir.

Ancak müşteri hafızasında kayıtlı ise dikkate alınabilir.

## RULE-005

Varsayılan servis tipi FTL (Komple Araç) olacaktır.

Parsiyel taşıma yalnızca müşteri talep ederse veya yük profili çok uygunsa değerlendirilir.

## RULE-006

Palet başına anormal ağırlık görüldüğünde sistem fiyat üretmez.

Ölçü ve ürün bilgisi ister.

## RULE-007

Makine yüklerinde ölçü ve ağırlık zorunludur.

## RULE-008

20 ton tekstil gibi standart yüklerde ölçü eksik olsa bile fiyat çalışılabilir.

## RULE-009

Aşağıdaki ifadeler Reefer ihtiyacını tetikler:

* Frozen
* Chilled
* Temperature Controlled
* Cold Chain
* +4°C
* -18°C

Tenteli elenir.

## RULE-010

Yük yüksekliği:

* > 2.85 m → Tenteli elenir
* 2.85 – 3.00 m → Mega değerlendirilir
* > 3.00 m → Lowbed / Project Cargo değerlendirilir

## RULE-011

Tek parça yük ≥ 26 ton ise:

Tenteli elenir.

Lowbed / Heavy Haul değerlendirilir.

## RULE-012

Aşağıdaki ifadeler Open Trailer değerlendirmesini tetikler:

* Overhead Crane
* Tavan Vinci
* Crane Loading
* Üstten Yükleme

## RULE-013

ADR Class 1 ve ADR Class 7 yüklerinde standart tenteli kullanılmaz.

Özel ADR ekipmanı gerekir.

## RULE-014

Dökme veya sıvı yüklerde:

* Tanker
* Damper
* Silobas

değerlendirilir.

## RULE-015

Yüksek hırsızlık riskli yüklerde:

* Elektronik
* Cep telefonu
* Yüksek değerli ürünler

Box Trailer değerlendirilir.

## RULE-016

Yük genişliği > 2.50 m ise:

Tenteli elenir.

Platform veya Lowbed değerlendirilir.

## RULE-017

Müşteri ürünü belirtmemişse ve müşteri geçmişi yüksek güvenle aynı ürünü gösteriyorsa AI ürünü tahmin edebilir.

Bu bilgi teklif üretiminde kullanılabilir.

## RULE-018

Müşteri adres belirtmemişse ve tek aktif yükleme adresi varsa sistem bunu kullanabilir.

## RULE-019

Birden fazla aktif yükleme adresi varsa sistem varsayım yapmaz.

Netleştirme ister.

## RULE-020

Müşteri yalnızca ülke belirttiyse ve geçmiş operasyonların %80'i aynı adrese gidiyorsa sistem ilgili adresi öneri olarak sunabilir.

## RULE-021

Supplier Selection Engine müşteri profilini dikkate alır.

Örneğin:

* Time Sensitive müşteri
* Price Sensitive müşteri

aynı tedarikçiyi farklı değerlendirebilir.

## RULE-022

Yeni müşteri operasyonları riskli kabul edilir.

İnsan onayı gerektirir.

## RULE-023

İmkânsız veya aşırı sıkışık transit süre talepleri riskli kabul edilir.

## RULE-024

ADR Class 1, ADR Class 7 ve Lithium Battery operasyonları riskli kabul edilir.

## RULE-025

Savaş, ambargo veya siyasi risk içeren bölgeler yönetim onayı gerektirir.

## RULE-026

Gabari dışı, proje kargo ve ağır yük operasyonları insan onayı gerektirir.

## RULE-027

Transit süre garantisi veya cezalı sözleşmeler yönetim incelemesi gerektirir.

## RULE-028

Akreditifli ve sıkı evrak şartlı gönderiler dokümantasyon incelemesi gerektirir.

## RULE-029

Cross-docking / aktarmalı operasyonlar hasar riski nedeniyle ekstra dikkat gerektirir.

## RULE-030

Resmi tatiller, dini bayramlar ve kritik tatil dönemleri operasyonel risk faktörü olarak değerlendirilir.

AI bu durumlarda kullanıcıyı uyarır ancak tek başına karar vermez.

RULE-031
Public email domain kullanan kontaklarda müşteri şirketi otomatik domain üzerinden belirlenmez.

RULE-032
Çok düzenli müşterilerde kişi adı / email ön eki müşteri tanıma için güçlü sinyaldir.

Örnek:
selman@temsa.com
→ Selman bilinen kontaksa
→ Customer = TEMSA

[RULE-033]
Road Freight fiyatı supplier’dan gelen güncel fiyatlara dayanır.

Geçmiş fiyatlar karar destek verisidir; ana fiyat kaynağı değildir.

RULE-034

Makine yüklerinde ölçü bilgisi eksikse sistem fiyat üretmez.

Müşteriden ölçü ve ağırlık bilgisi ister.


## RULE-031

Public email domain kullanan kontaklarda müşteri şirketi otomatik domain üzerinden belirlenmez.

Örnek public domainler:

* gmail.com
* hotmail.com
* outlook.com
* yahoo.com
* icloud.com

Bu domainler müşteri şirketi olarak kullanılmaz.

---

## RULE-032

Çok düzenli müşterilerde kişi adı / email ön eki müşteri tanıma için güçlü sinyal olabilir.

Örnek:

```text
selman@temsa.com
→ Selman bilinen kontaksa
→ Customer = TEMSA
```

Ancak bu kural yalnızca müşteri hafızası veya geçmiş kayıtlar ile destekleniyorsa uygulanır.

---

## RULE-033

Road Freight fiyatı supplier’dan gelen güncel fiyatlara dayanır.

Geçmiş fiyatlar karar destek verisidir; ana fiyat kaynağı değildir.

Geçmiş fiyatlar şu amaçlarla kullanılabilir:

* referans
* anomali tespiti
* route davranışı analizi
* müşteri / tedarikçi alışkanlığı analizi

Ancak geçmiş fiyat tek başına otomatik satış fiyatı üretmek için kullanılmaz.

---

## RULE-034

Critical missing information varsa sistem fiyat / teklif üretmez.

Bu durumda quote draft yerine clarification email hazırlanır.

Critical missing information örnekleri:

* Makine yükünde ölçü eksikliği
* Makine yükünde ağırlık eksikliği
* ADR bilgisi belirsizliği
* Pickup / delivery bilgisinin operasyonu başlatmaya yetmeyecek kadar eksik olması
* Ürün cinsinin ekipman kararını doğrudan etkilediği durumlarda commodity eksikliği

---

## RULE-035

Customer Memory profilleri yalnızca active = true ise recognition ve enrichment süreçlerinde kullanılabilir.

active = false olan profiller:

* UI’da görünür
* geçmiş bilgi olarak saklanır
* matching için kullanılmaz
* enrichment için kullanılmaz

---

## RULE-036

Customer Memory içindeki bilgi, müşterinin mailde açıkça verdiği bilginin üzerine yazmaz.

Öncelik sırası:

1. Müşterinin güncel mailde verdiği açık bilgi
2. Customer Memory varsayımı
3. AI çıkarımı
4. Clarification request

Örnek:

Müşteri mailde ekipmanı açıkça “reefer” olarak yazmışsa, Customer Memory’de default equipment “tenteli” olsa bile reefer dikkate alınır.

---

## RULE-037

Customer Memory kaynaklı varsayımlar kullanıcıya görünür şekilde açıklanır.

Sistem şu bilgileri göstermelidir:

* Customer Memory matched / not matched
* Source
* Matched By
* Applied Notes
* Kullanılan varsayımlar

Amaç:
Operasyon personeli AI’ın hangi bilgiyi nereden aldığını görebilmelidir.

---

## RULE-038

Test, Demo, Deneme, Sample, Example, Dummy gibi generic değerler müşteri adı veya alias olarak kullanılamaz.

Gerekçe:
Bu değerler AI parser tarafından belirsiz müşteri adı olarak üretilebilir.
Customer Memory içinde eşleşirse sistem müşteriyi yanlışlıkla tanınan müşteri kabul edebilir.

Geçerli test müşteri örnekleri:

* Sandbox Customer Alpha
* ACME Test Lojistik
* Dummy Customer 001

---

## RULE-039

AI parser çıktıları doğrudan operasyon kararına bağlanmaz.

Parser çıktıları önce normalization layer üzerinden geçirilir.

Amaç:

* farklı dillerdeki değerleri standartlaştırmak
* ekipman / ülke / yük tipi isimlerini canonical hale getirmek
* workflow kararlarını daha tutarlı hale getirmek

Örnek dönüşümler:

```text
machine → Makine
Turkey → Türkiye
Germany → Almanya
full truck / komple → FTL
partial / parsiyel → LTL
```

---

## RULE-040

Risk seviyesi aksiyon önerisini belirler.

Genel davranış:

```text
Green
→ quote_ready

Yellow
→ quote_with_review

Red
→ management_review

Critical missing information
→ clarification
```

Critical missing information varsa risk seviyesi yellow olsa bile fiyat üretimi durdurulur ve clarification email hazırlanır.

---

## RULE-041

AI müşteriyle doğrudan nihai teklif paylaşmaz.

AI’ın görevi:

* talebi analiz etmek
* eksik bilgi varsa sormak
* ekipman ve risk değerlendirmesi yapmak
* quote / clarification / management review draft üretmek
* önerilen aksiyonu göstermek

Son gönderim insan onayına bağlıdır.

## RULE-042 — Supplier Selection Is Not Price-Only

Supplier seçimi yalnızca en düşük fiyat kriterine göre yapılmamalıdır.

Sistem supplier seçerken aşağıdaki faktörleri birlikte değerlendirmelidir:

1. Route uygunluğu
2. Ekipman uygunluğu
3. Servis tipi uygunluğu
4. Yükün risk seviyesi
5. Supplier güvenilirliği
6. Fiyat rekabetçiliği
7. Hız / transit uygunluğu

Riskli taşımalarda güvenilirlik ve operasyonel uygunluk, fiyatın önüne geçebilir.

Örnekler:

* ADR veya yüksek riskli yüklerde uzman supplier önceliklendirilmelidir.
* Reefer yüklerde soğuk zincir kabiliyeti olmayan supplier elenmelidir.
* Lowbed / ağır yük taleplerinde proje yükü kabiliyeti olmayan supplier seçilmemelidir.
* Parsiyel taleplerde LTL / parsiyel network sağlayabilen supplier önceliklendirilmelidir.

Supplier Selection Engine en fazla 3 uygun supplier adayı önermelidir.

## RULE-043 — Supplier Capability Data Must Be Externalized

Supplier kabiliyetleri uzun vadede kod içine gömülü tutulmamalıdır.

Supplier seçimi için kullanılan bilgiler ayrı bir veri kaynağında tutulmalıdır.

İlk versiyonda bu veri kaynağı:

```text
data/supplier_capabilities.json
```

dosyasıdır.

Supplier capability datası aşağıdaki operasyonel alanları içermelidir:

```text
- Hangi ülke / bölge / hatta çalıştığı
- Hangi servis tiplerini desteklediği
- Hangi ekipmanları sağlayabildiği
- ADR / reefer / lowbed / parsiyel gibi özel kabiliyetleri
- Ana supplier mı, yedek supplier mı olduğu
- Güvenilirlik skoru
- Fiyat rekabetçiliği skoru
- Hız / transit uygunluğu skoru
```

Supplier seçimi yalnızca fiyat üzerinden yapılmamalıdır.

---

## RULE-044 — Critical Email Signals Require Safety Overrides

Kritik operasyonel sinyaller yalnızca AI parser sonucuna bırakılmamalıdır.

Ham email metninde açıkça görülen bazı bilgiler için deterministic safety override uygulanmalıdır.

Örnek kritik sinyaller:

```text
- ADR Class 1
- ADR Class 7
- Sıcaklık kontrollü taşıma ihtiyacı
- Lowbed / ağır yük ihtimali
- Teslim tarihi açısından imkânsız veya riskli termin
```

Özellikle ADR Class 1 ve ADR Class 7 gibi yüksek riskli yüklerde sistem, AI parser eksik veya hatalı dönse bile ham email metninden güvenlik kontrolü yapmalıdır.

Bu tür sinyaller tespit edildiğinde workflow daha güvenli aksiyonlara yönlendirilmelidir.

## RULE-045 — Selected Supplier and Quoted Supplier Must Match

Supplier Selection Engine tarafından seçilen supplier ile Supplier Quote içinde kullanılan supplier aynı olmalıdır.

Sistem bir taşıma talebi için supplier seçimi yaptıktan sonra, quote simülasyonu veya teklif hazırlığı farklı bir supplier adıyla devam etmemelidir.

Yanlış örnek:

```text id="k34pzb"
Supplier Selection: Anatolia Domestic
Supplier Quote: Demo Transport
```

Doğru örnek:

```text id="ai3cg2"
Supplier Selection: Anatolia Domestic
Supplier Quote: Anatolia Domestic
```

Bu kural demo/simülasyon ortamında da geçerlidir. Çünkü sistemin kendi çıktıları arasında görünen tutarsızlık kullanıcı güvenini zedeler.

Eğer Supplier Selection sonucu boşsa:

```text id="bdpkm4"
selected_suppliers = []
```

sistem ileride bunu ayrıca operasyonel uyarı veya consistency check olarak ele almalıdır.

Bu kuralın amacı, Supplier Selection ve Supplier Quote katmanları arasında temel operasyonel tutarlılığı sağlamaktır.

## RULE-046 — Capability-Based Service Validation

MINAI, supplier uygunluğunu supplier adı, açıklama metni veya tahmine dayalı ifadeler üzerinden değerlendirmemelidir.

Servis tipi uygunluğu, supplier capability datası üzerinden kontrol edilmelidir.

Özellikle LTL / parsiyel taşımalarda sistem şu mantıkla çalışmalıdır:

```text
Shipment service_type = LTL
Selected supplier = Local LTL Network
Supplier capability service_types contains LTL
Result = supplier is valid for LTL
```

Eğer seçilen supplier'ın capability datasında LTL desteği yoksa sistem uyarı üretmelidir:

```text
Selected supplier capability does not support LTL.
```

Eğer seçilen supplier için capability datası bulunamıyorsa sistem bunu da açıkça belirtmelidir:

```text
Supplier capability data not found.
LTL support must be verified.
```

Bu kural FTL, LTL, reefer, ADR ve ileride eklenecek diğer servis tipleri için de geçerlidir.

Sistem bilmediği bir capability bilgisini varmış gibi kabul etmemelidir.

Doğru karar seviyesi:

```text
Known yes  → kullanılabilir
Known no   → elenir veya warning üretir
Unknown    → doğrulama warning'i üretir
```

## RULE-047 — Raw Email Commodity Signals Override Generic AI Commodity

Müşteri mailinde açık ve güvenilir bir ürün ifadesi varsa, bu ifade AI parser tarafından üretilen daha genel commodity değerinin üstünde önceliğe sahip olmalıdır.

Sistem şu tür durumlarda AI çıktısını deterministik olarak düzeltmelidir:

```text
Mailde: içecek
AI commodity: Gıda
Final commodity: İçecek / Meşrubat
```

```text
Mailde: trafo
AI commodity: Makine
Final commodity: Elektrik Transformatörü
```

Bu kuralın amacı, açık ürün sinyallerinin daha genel sınıflara indirgenmesini engellemektir.

İlk desteklenen commodity override grupları:

```text
içecek / icecek / meşrubat / mesrubat  → İçecek / Meşrubat
trafo / transformatör / transformer    → Elektrik Transformatörü
tekstil / textile / kumaş              → Tekstil
makine / makina / machine              → Makine
```

Bu kural yalnızca müşteri mailinde açıkça görünen güçlü ürün sinyalleri için uygulanmalıdır.

Sistem belirsiz ürün ifadelerinde commodity uydurmamalıdır. Belirsizlik varsa mevcut AI parser çıktısı korunmalı veya eksik bilgi / doğrulama sorusu üretilmelidir.

Bu yapı MVP aşamasında kod içi safety override olarak tutulabilir. Ürünleşme aşamasında commodity keyword ve alias kayıtları ayrı bir data kaynağına veya database tablosuna taşınmalıdır.

## RULE-048 — Customer-Provided GTIP Codes Are Interpreted, Not Assigned

MINAI müşteri tarafından açıkça verilen GTİP / HS kodlarını okuyabilir ve operasyonel olarak yorumlayabilir.

Ancak MINAI kesin GTİP tayini yapmamalıdır.

Doğru davranış:

```text
Müşteri mailinde GTİP kodu varsa:
- Kod normalize edilir.
- HS chapter / heading / subheading ayrıştırılır.
- Kod mevcut commodity map içinde aranır.
- Uygun operasyonel commodity grubu önerilir.
```

Örnek:

```text
GTİP: 2202.10.00.00.00
Final commodity: İçecek / Meşrubat
```

Yanlış davranış:

```text
MINAI bu ürünün kesin GTİP kodu budur.
```

Bu kuralın amacı, GTİP bilgisini operasyonel fayda için kullanmak ama sistemi gümrük müşaviri gibi konumlandırmamaktır.

Eğer müşteri ürün açıklaması ile GTİP kodu arasında bariz bir uyumsuzluk varsa sistem ileride operasyonel uyarı üretmelidir.

Örnek uyumsuzluk:

```text
Ürün açıklaması: plastik poşet
GTİP: 8504...
```

Bu durumda sistem sessizce karar vermemeli, doğrulama istemelidir.

MVP v1 kapsamında GTİP kodları şu amaçlarla kullanılabilir:

```text
1. Commodity sınıflandırmasını güçlendirmek
2. Ürün ailesini anlamak
3. Operasyonel not üretmek
4. İleride evrak / uygunluk uyarılarını tetiklemek
5. Customer memory içinde müşterinin sık kullandığı GTİP kodlarını öğrenmek
```
## RULE-049 — GTIP and Product Description Conflicts Must Be Flagged

Müşteri mailinde verilen GTİP / HS kodu ile ürün açıklaması arasında bariz uyumsuzluk varsa MINAI bunu operasyonel uyarı olarak işaretlemelidir.

Sistem böyle durumlarda GTİP koduna göre commodity değerini körlemesine değiştirmemelidir.

Örnek:

```text
Ürün açıklaması: plastik poşet
GTİP: 8504.21.00.00.00
```

Bu GTİP kodu elektrik transformatörü / elektrik ekipmanı grubuna işaret ederken, ürün açıklaması plastik ürün grubuna işaret eder.

Doğru davranış:

```text
Final commodity: Plastik Ürünler
Operational warning: GTIP kodu ile ürün açıklaması uyumsuz görünüyor.
```

Yanlış davranış:

```text
Final commodity: Elektrik Transformatörü
Warning yok
```

Bu kuralın amacı, müşteri tarafından hatalı veya uyumsuz girilmiş GTİP kodlarının sessizce operasyonel karara dönüşmesini engellemektir.

MINAI bu durumda müşteri veya gümrük müşaviri doğrulaması gerektiğini belirtmelidir.
## RULE-050 — Commodity Keywords Must Be Data-Driven

MINAI ürün tipi kelime eşleşmelerini Python kodu içine gömülü sabit listelerden yönetmemelidir.

Commodity keyword / alias eşleşmeleri data-driven olmalıdır.

Doğru yapı:

```text
data/commodity_dictionary.json
```

Örnek:

```text
keyword: içecek
canonical_commodity: İçecek / Meşrubat
```

Yanlış yapı:

```text
email_parser.py içinde hard-coded commodity keyword listesi
```

Bu kuralın amacı, yeni ürün tipleri eklendikçe parser kodunun sürekli değiştirilmesini engellemektir.

MVP aşamasında commodity dictionary JSON dosyasında tutulabilir. Ürünleşme aşamasında bu yapı database, admin panel veya müşteri/operasyon öğrenme sistemiyle yönetilmelidir.

MINAI yeni bir ürün tipiyle karşılaştığında kod değiştirmemeli; yeni alias / commodity önerisini data katmanına eklenebilir hale getirmelidir.
## RULE-051 — MVP Commodity Dictionary Should Cover Operationally Relevant Product Groups

MVP aşamasında commodity dictionary, sonsuz ürün listesi olmaya çalışmamalıdır.

Bunun yerine operasyonel kararı etkileyen ürün gruplarını kapsamalıdır.

Bir ürün grubu commodity dictionary’ye eklenirken şu sorular dikkate alınmalıdır:

```text
Bu ürün ekipman seçimini etkiliyor mu?
Risk seviyesini etkiliyor mu?
Eksik bilgi sorusunu değiştiriyor mu?
Belge / uygunluk uyarısı gerektiriyor mu?
Supplier seçimini etkiliyor mu?
Customer memory için anlamlı mı?
```

Commodity dictionary’ye eklenen her ürün grubu şu yapıya sahip olmalıdır:

```text
canonical_commodity
keywords
notes
```

Örnek:

```text
canonical_commodity: Kimyasal Ürün
keywords: kimyasal, chemical, solvent, boya
notes: ADR durumu, MSDS/SDS belgesi ve ambalaj uygunluğu kontrol edilmelidir.
```

Bu kuralın amacı, MINAI’nin ürün tanıma kabiliyetini operasyonel faydaya göre büyütmektir.

Commodity dictionary yalnızca kelime listesi değildir; ileride risk, ekipman, belge ve müşteri alışkanlığı kararlarının temel veri kaynaklarından biri olacaktır.
## RULE-052 — Commodity Recognition Must Trigger Operational Reflexes

MINAI bir ürün grubunu tanıdığında sadece commodity alanını doldurmakla yetinmemelidir.

Commodity tanıma sonucunda gerekiyorsa operasyonel refleks üretmelidir.

Operasyonel refleks örnekleri:

```text
Dondurulmuş Gıda:
- Reefer ekipman değerlendirilmeli
- Sıcaklık derecesi kontrol edilmeli
- Soğuk zincir riski dikkate alınmalı

Kimyasal Ürün:
- ADR durumu kontrol edilmeli
- MSDS/SDS belgesi istenmeli
- Ambalaj ve etiketleme uygunluğu doğrulanmalı

Cam / Kırılabilir:
- Ambalaj kontrol edilmeli
- Sabitleme / lashing ihtiyacı değerlendirilmeli
- Hasar riski dikkate alınmalı

Elektronik:
- Yüksek değer riski değerlendirilmeli
- Hırsızlık ve hassasiyet riski kontrol edilmeli
- Gerekirse kapalı kasa / güvenli taşıma düşünülmeli

İlaç / Pharma:
- Sıcaklık gereksinimi doğrulanmalı
- Ruhsat / uygunluk belgeleri kontrol edilmeli
- Özel taşıma şartları netleştirilmeli
```

Commodity operational profile şu amaçlarla kullanılmalıdır:

```text
1. Risk seviyesi belirleme
2. Human review gerekip gerekmediğini belirleme
3. Ekipman önerisini destekleme
4. Operasyon notu üretme
5. Eksik bilgi sorularını ileride daha akıllı hale getirme
```

Bu kuralın amacı, MINAI’nin “ürünü tanıyan bot” seviyesinde kalmasını engellemektir.

MINAI ürün tipini tanıdığında, o ürünün freight forwarding operasyonunda ne anlama geldiğini de yorumlamalıdır.
## RULE-053 — Commodity Profiles May Add Critical Missing Information

MINAI’de bazı ürün grupları, standart teklif alanlarına ek olarak kritik bilgi gerektirebilir.

Bu bilgiler commodity operational profile üzerinden tanımlanmalıdır.

Örnek:

```text
Kimyasal Ürün:
- MSDS/SDS belgesi
- ADR durumu
- Ambalaj tipi ve ambalaj uygunluğu
```

Bir commodity profile içinde `critical_missing_info_fields` tanımlanmışsa, bu alanlar eksik olduğunda sistem fiyat çalışmasına doğrudan devam etmemelidir.

Bu durumda doğru aksiyon:

```text
result_type: clarification
action_type: clarification
```

Müşteriden eksik bilgiler istenmeli ve bilgiler tamamlanmadan teklif paylaşılmamalıdır.

Bu kuralın amacı, MINAI’nin yalnızca genel eksik bilgi kontrolü yapmasını değil, ürün grubuna özel operasyonel eksik bilgileri de yakalamasını sağlamaktır.

Commodity profile kaynaklı missing info kuralları özellikle şu ürün gruplarında kullanılmalıdır:

```text
Kimyasal Ürün
İlaç / Pharma
Medikal Ürün
Cam / Kırılabilir
Dondurulmuş Gıda
Yüksek değerli elektronik
```

MINAI, ürün tipini tanıdığında o ürün için gerekli kritik operasyonel bilgileri de sorgulamalıdır.
## RULE-054 — High-Sensitivity Commodities Require Product-Specific Clarification

MINAI, operasyonel hassasiyeti yüksek ürün gruplarında yalnızca genel eksik bilgi kontrolüyle yetinmemelidir.

High-sensitivity commodity grupları için ürün tipine özel clarification soruları tanımlanmalıdır.

Örnek ürün grupları:

```text
İlaç / Pharma
Medikal Ürün
Kimyasal Ürün
Dondurulmuş Gıda
Cam / Kırılabilir
Elektronik
```

Bu ürün gruplarında gerekli bilgiler ürün tipine göre değişir.

Örnek:

```text
İlaç / Pharma:
- Sıcaklık gereksinimi
- Uygunluk / ruhsat belgeleri
- Özel taşıma şartları

Dondurulmuş Gıda:
- Sıcaklık derecesi
- Reefer gereksinimi
- Soğuk zincir hassasiyeti

Cam / Kırılabilir:
- Ambalaj tipi
- İstiflenebilirlik
- Sabitleme / lashing ihtiyacı

Elektronik:
- Yaklaşık ürün değeri
- Ambalaj ve darbe hassasiyeti
- Güvenli taşıma / kapalı kasa ihtiyacı
```

Bir commodity profile içinde `critical_missing_info_fields` tanımlanmışsa, bu bilgiler eksik olduğunda sistem teklif üretimini durdurmalı ve clarification akışına geçmelidir.

Doğru davranış:

```text
result_type: clarification
action_type: clarification
```

Bu kuralın amacı, MINAI’nin ürün tipine göre operasyonel olarak anlamlı sorular sormasını sağlamaktır.

MINAI, yüksek hassasiyetli ürünlerde “bilgi yeterli görünüyor” yanılgısına düşmemeli; ürün grubunun gerektirdiği kritik detayları ayrıca kontrol etmelidir.
## RULE-055 — Action Recommendations Must Include Commodity-Specific Checks

MINAI’nin action recommendation çıktısı yalnızca genel operasyon checklist’i içermemelidir.

Bir shipment’ın commodity profile’ında `action_checklist` tanımlıysa, bu maddeler operasyoncuya verilen checklist içine eklenmelidir.

Örnek:

```text
İlaç / Pharma:
- Sıcaklık gereksinimini müşteriyle doğrula.
- Uygunluk / ruhsat belgelerini kontrol et.
- Özel taşıma şartlarını netleştir.

Kimyasal Ürün:
- MSDS/SDS belgesini kontrol et.
- ADR durumunu müşteriyle doğrula.
- Ambalaj ve etiketleme uygunluğunu kontrol et.

Dondurulmuş Gıda:
- Reefer ekipman uygunluğunu doğrula.
- Sıcaklık derecesini müşteriyle teyit et.
- Soğuk zincir hassasiyetini kontrol et.
```

Bu kuralın amacı, action recommendation çıktısının ürün tipine göre operasyonel olarak anlamlı hale gelmesini sağlamaktır.

MINAI bir ürünü tanıdığında, operasyoncuya o ürün için dikkat edilmesi gereken özel kontrolleri de göstermelidir.

Genel checklist korunmalı, commodity-specific checklist maddeleri bu listeye eklenmelidir.

Aynı madde birden fazla kaynaktan gelirse tekrar edilmemelidir.
## RULE-056 — UI Must Surface Operational Action Items Clearly

MINAI UI, backend tarafından üretilen operasyonel aksiyonları açık ve uygulanabilir şekilde göstermelidir.

Action recommendation içinde yer alan checklist maddeleri operasyoncu için görünür olmalıdır.

UI şu bilgileri net göstermelidir:

```text id="e7de67"
Aksiyon tipi
Öncelik
Aksiyon kaynağı
Operasyon kontrol listesi
Risk nedenleri
Eksik bilgi alanları
Eksik bilgi nedeni
```

Eksik bilgi alanları internal field code olarak gösterilmemelidir.

Örnek yanlış gösterim:

```text id="b7tibg"
pharma temperature requirement
pharma compliance document
```

Örnek doğru gösterim:

```text id="abb82g"
İlaç / pharma yükü için sıcaklık gereksinimi
İlaç / pharma uygunluk veya ruhsat belgeleri
```

Commodity profile kaynaklı checklist maddeleri genel checklist içinde kaybolmamalıdır. UI, bu listenin hem genel operasyon kontrollerini hem de ürün tipine özel kontrolleri içerdiğini açıkça belirtmelidir.

Bu kuralın amacı, MINAI’nin operasyonel kararlarını sadece backend çıktısı olarak üretmesini değil, operasyoncunun günlük iş akışında kullanabileceği şekilde görünür kılmasını sağlamaktır.
## RULE-057 — UI Must Expose Commodity Operational Profile

MINAI UI, shipment’ın commodity operational profile bilgisini operasyoncuya açık şekilde göstermelidir.

Commodity profile yalnızca backend içinde kullanılan teknik bir yapı olarak kalmamalıdır.

UI’da gösterilmesi gereken başlıca bilgiler:

```text
Commodity adı
Human review gerekip gerekmediği
Reefer / özel ekipman ihtiyacı
High value adayı olup olmadığı
Varsayılan ekipman veya sıcaklık bilgisi
Risk reason
Operational notes
Profile-driven missing info alanları
Profile action checklist
```

Profile-driven missing info alanları kritik ise UI’da açıkça ayrıştırılmalıdır.

Örnek:

```text
🔴 İlaç / pharma yükü için sıcaklık gereksinimi
🔴 İlaç / pharma uygunluk veya ruhsat belgeleri
🔴 İlaç / pharma özel taşıma şartları
```

Bu kuralın amacı, MINAI’nin ürün tipine göre verdiği operasyonel refleksleri kullanıcıya görünür kılmaktır.

Operasyoncu yalnızca “sarı risk” veya “eksik bilgi” sonucu görmemeli; bu sonucun hangi commodity profile’dan kaynaklandığını da anlayabilmelidir.
## RULE-058 — API Responses Must Preserve UI-Critical Operational Profile Data

MINAI API response’ları, UI’ın operasyonel kararları göstermek için ihtiyaç duyduğu kritik datayı korumalıdır.

`commodity_profile` UI açısından kritik bir response alanıdır.

Bu alan şu bilgileri içerebilmelidir:

```text
canonical_commodity
notes
operational_profile
risk_reason
missing_info_fields
critical_missing_info_fields
action_checklist
```

UI’da gösterilen commodity profile paneli bu dataya bağlıdır.

Bu nedenle `commodity_profile` alanı API response içinden kaldırılmamalı veya eksik döndürülmemelidir.

Yeni API response değişikliklerinde şu kontrol yapılmalıdır:

```text
UI bu alanı kullanıyor mu?
Test suite bu alanın varlığını doğruluyor mu?
Alan eksikse operasyoncu ekranında kritik bilgi kaybolur mu?
```

Bu kuralın amacı, backend response kontratını UI’ın operasyonel ihtiyaçlarıyla uyumlu tutmaktır.

MINAI’de UI-critical alanlar yalnızca teknik JSON detayı sayılmamalı; regression test ile korunmalıdır.
## RULE-059 — Commodity Dictionary Must Be Validated

MINAI commodity dictionary datası otomatik validation olmadan büyütülmemelidir.

`data/commodity_dictionary.json` dosyası operasyonel karar datası içerir ve şu alanları etkiler:

```text id="o9jm5u"
Commodity recognition
Risk assessment
Equipment decision
Missing information
Clarification draft
Action recommendation checklist
UI commodity profile panel
```

Bu nedenle dictionary’ye yeni ürün, keyword veya operational profile eklenirken validator temiz geçmelidir.

Validator şu dosyada tutulur:

```text id="mndn6l"
src/core/commodity_dictionary_validator.py
```

Validation kuralları en az şunları kontrol etmelidir:

```text id="gitpas"
canonical_commodity dolu olmalı.
keywords liste olmalı ve boş olmamalı.
Aynı commodity içinde duplicate keyword olmamalı.
notes liste olmalı.
operational_profile dict olmalı.
missing_info_fields liste olmalı.
critical_missing_info_fields liste olmalı.
critical_missing_info_fields içindeki alanlar missing_info_fields içinde de yer almalı.
action_checklist liste olmalı.
Boolean profile alanları boolean olmalı.
String profile alanları boş olmamalı.
```

Commodity dictionary validation test suite içinde çalışmalıdır.

Dictionary invalid ise test suite fail vermelidir.

Bu kuralın amacı, MINAI’nin data-driven operasyon kararlarının sessiz veri hatalarıyla bozulmasını engellemektir.
