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

`gross_weight_kg` shipment toplam brüt ağırlığıdır ve tek başına
tek-parça ağırlığı olarak yorumlanmaz. Package adedi tam olarak 1 ise
shipment gross weight tek-parça kontrolünde kullanılabilir. Quantity > 1 olan
package-line `weight_kg` alanı mevcut kontratta parça başı veya satır toplamı
olabileceğinden, 26 ton eşiğini geçiyorsa ekipman atamadan önce netleştirme
istenir.

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

---

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

Eligibility skordan önce uygulanır:

* Origin country desteği tek başına route uygunluğu sağlamaz.
* Exact `priority_routes` tam route desteğidir.
* Destination country ile non-domestic `route_regions` birlikteyse bölgesel route desteği kabul edilir.
* Yalnızca `domestic` route region taşıyan supplier uluslararası hatta kullanılmaz.
* Açık servis tipi veya zorunlu ekipman uyumsuzluğu supplier'ı düşük skorla tutmaz; eler.
* Supplier isimlerinden route, reefer veya domestic kabiliyeti türetilmez.

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
## RULE-060 — Data Health Panels Are Read-Only Unless Explicitly Approved

MINAI’de data health panelleri varsayılan olarak sadece okuma amaçlı olmalıdır.

Commodity dictionary, customer memory, supplier capability matrix veya benzeri operasyonel data kaynakları UI’da gösterilebilir.

Ancak bu paneller açık onay olmadan data değiştirmemelidir.

Özellikle şu data kaynaklarında dikkatli olunmalıdır:

```text
data/commodity_dictionary.json
data/supplier_capabilities.json
customer memory profiles
HS / GTIP mapping data
```

Read-only data health panelleri şu amaçla kullanılmalıdır:

```text
Validation sonucu göstermek
Hata ve uyarıları görünür yapmak
Data sayısını göstermek
Teknik JSON preview sağlamak
Operasyonel data bozulmalarını erken fark etmek
```

Edit, import, delete veya otomatik düzeltme özellikleri ayrı task olarak ele alınmalı ve açıkça onaylanmalıdır.

Bu kuralın amacı, operasyonel karar datasının yanlışlıkla UI üzerinden bozulmasını engellemektir.
## RULE-061 — Supplier Capability Matrix Must Be Validated

MINAI supplier capability matrix datası otomatik validation olmadan büyütülmemelidir.

`data/supplier_capabilities.json` dosyası operasyonel supplier seçim datası içerir.

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

Bu nedenle supplier datasına yeni kayıt, rota, ekipman, servis tipi veya skor eklenirken validator temiz geçmelidir.

Validator şu dosyada tutulur:

```text
src/core/supplier_capability_validator.py
```

Validation kuralları en az şunları kontrol etmelidir:

```text
supplier_name dolu olmalı.
supplier_name duplicate olmamalı.
active boolean olmalı.
role geçerli değerlerden biri olmalı.
route_regions liste olmalı.
countries liste olmalı.
service_types liste olmalı.
equipment_types liste olmalı.
special_capabilities liste olmalı.
priority_routes liste olmalı.
reliability_score, price_score ve speed_score 0-1 aralığında sayı olmalı.
notes dolu string olmalı.
En az bir active supplier bulunmalı.
En az bir active FTL supplier bulunmalı.
```

Coverage eksiklikleri ayrıca warning olarak raporlanmalıdır:

```text
LTL coverage yoksa warning.
Reefer coverage yoksa warning.
ADR coverage yoksa warning.
```

Supplier capability validation test suite içinde çalışmalıdır.

Supplier capability matrix invalid ise test suite fail vermelidir.

Bu kuralın amacı, MINAI’nin supplier selection kararlarının sessiz veri hatalarıyla bozulmasını engellemektir.
## RULE-062 — Supplier Data Health Must Be Visible in UI

MINAI’de supplier capability matrix sağlığı UI üzerinden görülebilir olmalıdır.

`data/supplier_capabilities.json` dosyası operasyonel supplier seçim datası içerir.

Bu data şu alanları etkiler:

```text
Supplier selection
Route capability
Equipment capability
Risk fit
Supplier quote simulation
Operational consistency checks
UI supplier selection display
```

Bu nedenle supplier data health paneli şu bilgileri göstermelidir:

```text
Supplier sayısı
Active supplier sayısı
FTL coverage
LTL coverage
Reefer coverage
ADR coverage
Validation errors
Validation warnings
Raw validation result
```

Supplier data health paneli varsayılan olarak read-only olmalıdır.

Supplier ekleme, supplier silme, skor değiştirme veya capability edit etme özellikleri ayrı task olarak ele alınmalı ve açıkça onaylanmalıdır.

Bu kuralın amacı, supplier selection kararlarını etkileyen veri sağlığını görünür yapmak ve operasyonel data bozulmalarını erken yakalamaktır.
## RULE-063 — Data Health Checks Should Be Grouped in One UI Area

MINAI’de data health kontrolleri UI içinde dağınık halde tutulmamalıdır.

Test suite, dictionary validation, supplier matrix validation ve benzeri sağlık kontrolleri mümkün olduğunca tek bir ana bölüm altında gruplanmalıdır.

Varsayılan ana bölüm:

```text
Data Sağlığı Dashboard
```

Bu dashboard şu tür kontrolleri içerebilir:

```text
Automated test suite
Commodity dictionary validation
Supplier capability validation
Customer memory validation
HS / GTIP mapping validation
Future data source health checks
```

Yeni data health kontrolü eklendiğinde önce mevcut dashboard’a yeni sekme olarak eklenmesi düşünülmelidir.

Ayrı sayfa veya ayrı panel ancak açık ihtiyaç varsa tercih edilmelidir.

Bu kuralın amacı, UI’ın büyüdükçe dağılmasını engellemek ve operasyonel sağlık kontrollerini tek merkezde görünür tutmaktır.
## RULE-064 — Customer Memory Must Be Validated

MINAI customer memory datası otomatik validation olmadan büyütülmemelidir.

`data/customer_memory.json` dosyası müşteri tanıma ve müşteri özel operasyon kararları için kritik data içerir.

Bu data şu alanları etkiler:

```text id="dwjlls"
Customer recognition
Alias matching
Default commodity
Default equipment
Default pickup / delivery information
Price sensitivity
Time sensitivity
Risk assessment
Operational notes
```

Bu nedenle customer memory’ye yeni müşteri, alias veya varsayılan operasyon bilgisi eklenirken validator temiz geçmelidir.

Validator şu dosyada tutulur:

```text id="i56wde"
src/core/customer_memory_validator.py
```

Validation kuralları en az şunları kontrol etmelidir:

```text id="d97c4d"
customer_name dolu olmalı.
customer_name duplicate olmamalı.
active boolean olmalı.
aliases liste olmalı.
Aynı müşteri içinde duplicate alias olmamalı.
Aynı alias iki farklı müşteri tarafından kullanılmamalı.
Alias başka bir customer_name ile çakışmamalı.
price_sensitivity geçerli değerlerden biri olmalı.
time_sensitivity geçerli değerlerden biri olmalı.
operational_notes liste olmalı.
```

Customer memory validation test suite içinde çalışmalıdır.

Customer memory invalid ise test suite fail vermelidir.

Bu kuralın amacı, MINAI’nin müşteri hafızası kaynaklı yanlış eşleşme ve yanlış operasyonel karar riskini azaltmaktır.
## RULE-065 — Customer Memory Data Health Must Be Visible in UI

MINAI’de customer memory data sağlığı UI üzerinden görülebilir olmalıdır.

`data/customer_memory.json` dosyası müşteri tanıma ve müşteri özel operasyon kararları için kritik data içerir.

Bu data şu alanları etkiler:

```text id="b29j0q"
Customer recognition
Alias matching
Default commodity
Default equipment
Default pickup / delivery information
Price sensitivity
Time sensitivity
Risk assessment
Operational notes
```

Bu nedenle customer memory data health paneli şu bilgileri göstermelidir:

```text id="xwc7cr"
Profile sayısı
Active profile sayısı
Alias sayısı
Validation errors
Validation warnings
Raw validation result
```

Customer memory data health paneli varsayılan olarak read-only olmalıdır.

Müşteri ekleme, müşteri silme, alias değiştirme veya otomatik düzeltme özellikleri ayrı task olarak ele alınmalı ve açıkça onaylanmalıdır.

Bu kuralın amacı, customer memory kaynaklı yanlış müşteri eşleşmesi ve yanlış operasyonel karar risklerini erken görünür hale getirmektir.
## RULE-066 — HS / GTIP Mapping Must Be Validated

MINAI HS / GTIP mapping datası otomatik validation olmadan büyütülmemelidir.

`data/hs_commodity_map.json` dosyası müşterinin verdiği GTIP / HS kodlarını operasyonel commodity gruplarına bağlayan kritik data içerir.

Bu data şu alanları etkiler:

```text id="ua8gh4"
GTIP interpretation
Commodity classification
GTIP consistency warning
Operational notes
Risk assessment
Missing information behavior
```

Bu nedenle HS / GTIP mapping’e yeni chapter, heading veya subheading eklenirken validator temiz geçmelidir.

Validator şu dosyada tutulur:

```text id="m0z6mx"
src/core/hs_commodity_map_validator.py
```

Validation kuralları en az şunları kontrol etmelidir:

```text id="g4wmd7"
Root yapı dict / object olmalı.
En az bir mapping bulunmalı.
HS kodları yalnızca rakamlardan oluşmalı.
HS kod uzunluğu 2, 4 veya 6 karakter olmalı.
commodity_group dolu olmalı.
notes varsa liste olmalı.
notes içindeki maddeler boş olmayan string olmalı.
Duplicate HS code key yakalanmalı.
```

Coverage ve uyumluluk eksikleri ayrıca warning olarak raporlanmalıdır:

```text id="744ycd"
Heading kaydı varsa parent chapter yoksa warning.
Subheading kaydı varsa parent heading veya parent chapter yoksa warning.
commodity_group commodity dictionary canonical değerleriyle birebir eşleşmiyorsa warning.
```

HS / GTIP mapping validation test suite içinde çalışmalıdır.

HS / GTIP mapping invalid ise test suite fail vermelidir.

Bu kuralın amacı, MINAI’nin GTIP kaynaklı commodity yorumlarının sessiz veri hatalarıyla bozulmasını engellemektir.
## RULE-067 — HS / GTIP Mapping Data Health Must Be Visible in UI

MINAI’de HS / GTIP mapping data sağlığı UI üzerinden görülebilir olmalıdır.

`data/hs_commodity_map.json` dosyası GTIP / HS kodlarını operasyonel commodity gruplarına bağlayan kritik data içerir.

Bu data şu alanları etkiler:

```text
GTIP interpretation
Commodity classification
GTIP consistency warning
Operational notes
Risk assessment
Missing information behavior
```

Bu nedenle HS / GTIP mapping data health paneli şu bilgileri göstermelidir:

```text
Mapping sayısı
Chapter sayısı
Heading sayısı
Subheading sayısı
Canonical commodity coverage
Validation errors
Validation warnings
Raw validation result
```

HS / GTIP mapping data health paneli varsayılan olarak read-only olmalıdır.

Mapping ekleme, mapping silme, commodity_group değiştirme veya otomatik düzeltme özellikleri ayrı task olarak ele alınmalı ve açıkça onaylanmalıdır.

Bu kuralın amacı, GTIP kaynaklı yanlış commodity yorumu ve yanlış operasyonel uyarı risklerini erken görünür hale getirmektir.
## RULE-068 — Data Health Summary Must Aggregate Validator Results

MINAI’de kritik data kaynakları için üretilen validator sonuçları merkezi bir data health summary altında toplanmalıdır.

Varsayılan summary endpoint:

```text id="a3lk2u"
GET /data-health/summary
```

Bu endpoint en az şu validator sonuçlarını kapsamalıdır:

```text id="hkc3i2"
Commodity Dictionary
Supplier Capability Matrix
Customer Memory
HS / GTIP Mapping
```

Summary response şu genel alanları sağlamalıdır:

```text id="n3v3vm"
overall_valid
total_checks
valid_checks
invalid_checks
total_errors
total_warnings
checks
```

Yeni bir data validator eklendiğinde şu adımlar düşünülmelidir:

```text id="fyve6i"
Validator test suite’e bağlandı mı?
Validator için read-only endpoint var mı?
Validator sonucu /data-health/summary içine eklendi mi?
UI Data Sağlığı Dashboard bunu gösterecek mi?
```

Bu kuralın amacı, data health bilgisinin dağılmasını engellemek ve MINAI’nin operasyonel data sağlığını tek merkezden izlenebilir hale getirmektir.
## RULE-069 — Data Health Dashboard Must Show Overall Summary

MINAI Data Sağlığı Dashboard, detay sekmelerine ek olarak genel data health summary göstermelidir.

Summary en az şu alanları içermelidir:

```text
Overall Valid
Valid Checks
Errors
Warnings
Kontrol Özeti
Raw Summary
```

Summary verisi merkezi endpoint üzerinden alınmalıdır:

```text
GET /data-health/summary
```

Dashboard’da ayrı validator sekmeleri korunmalıdır, ancak kullanıcı önce genel durumu görebilmelidir.

Yeni validator eklendiğinde şu kontroller yapılmalıdır:

```text
Validator /data-health/summary içine eklendi mi?
Dashboard summary toplamları yeni validator’ı kapsıyor mu?
Detay sekmesi gerekiyorsa Data Sağlığı Dashboard’a eklendi mi?
```

Bu kuralın amacı, operasyonel data sağlığının tek bakışta anlaşılmasını ve detayların gerektiğinde incelenmesini sağlamaktır.
## RULE-070 — Data Health Summary Must Show Last Checked Time

MINAI Data Sağlığı Dashboard, summary bilgisinin ne zaman kontrol edildiğini göstermelidir.

Dashboard summary alanı en az şu bilgileri içermelidir:

```text
Overall Valid
Valid Checks
Errors
Warnings
Last checked
Manual refresh button
```

Kullanıcı, data health summary sonucunu sayfayı tamamen yenilemeden manuel olarak tekrar çağırabilmelidir.

Varsayılan refresh butonu:

```text
Refresh Data Health Summary
```

Summary sonucu UI içinde kısa süreli state olarak saklanabilir.

Bu kuralın amacı, kullanıcının data health bilgisinin güncelliğini anlayabilmesini ve gerektiğinde hızlıca tekrar kontrol edebilmesini sağlamaktır.
## RULE-071 — Data Health Logic Should Live Outside API Layer

MINAI’de data health summary üretim mantığı API katmanında tutulmamalıdır.

Data health summary için merkezi core servis kullanılmalıdır:

```text
src/core/data_health.py
```

API endpoint sadece bu core servisi çağırmalıdır:

```text
GET /data-health/summary
```

Data health summary en az şu validator sonuçlarını merkezi olarak toplamalıdır:

```text
Commodity Dictionary
Supplier Capability Matrix
Customer Memory
HS / GTIP Mapping
```

Yeni validator eklendiğinde şu yerler kontrol edilmelidir:

```text
src/core/data_health.py
test suite
Data Sağlığı Dashboard
ilgili API endpoint
dokümantasyon
```

Bu kuralın amacı, API katmanını sade tutmak ve operasyonel data health mantığını test edilebilir core servis olarak yönetmektir.
## RULE-072 — Data Health Summary Contract Must Be Tested

MINAI’de data health summary response yapısı regression test ile korunmalıdır.

Summary contract en az şu alanları içermelidir:

```text id="kmmd72"
overall_valid
total_checks
valid_checks
invalid_checks
total_errors
total_warnings
checks
```

Regression test şu validator check isimlerini doğrulamalıdır:

```text id="xm1n1t"
commodity_dictionary
supplier_capabilities
customer_memory
hs_commodity_map
```

Yeni validator eklendiğinde şu yerler birlikte güncellenmelidir:

```text id="t9mdki"
src/core/data_health.py
evaluate_data_health_summary()
Data Sağlığı Dashboard
ilgili API endpoint
dokümantasyon
```

Bu kuralın amacı, UI ve API arasında kullanılan data health summary contract’ının sessizce bozulmasını engellemektir.
## RULE-073 — Data Health Summary Must Expose Warning Details

MINAI Data Sağlığı Dashboard, summary alanında sadece toplam warning/error sayılarını değil, detaylarını da göstermelidir.

Summary UI en az şu bilgileri göstermelidir:

```text id="5y4ibm"
Total errors
Total warnings
Validator bazlı error listesi
Validator bazlı warning listesi
Raw summary
```

Warning/error detayları kullanıcıyı detay sekmelerine girmeye zorlamadan görülebilmelidir.

Validator bazlı gösterim tercih edilmelidir:

```text id="5kry5y"
Commodity Dictionary
Supplier Capability Matrix
Customer Memory
HS / GTIP Mapping
```

Yeni validator eklendiğinde summary warning/error detayları içinde otomatik veya açık şekilde görünmelidir.

Bu kuralın amacı, data health uyarılarının sayısal olarak değil, operasyonel olarak anlaşılabilir şekilde görünmesini sağlamaktır.
## RULE-074 — Data Health UI Labels Must Be Human-Friendly

MINAI Data Sağlığı Dashboard, teknik alan adlarını kullanıcı ekranında doğrudan göstermemelidir.

UI’da kullanıcı dostu operasyon dili tercih edilmelidir.

Örnek label dönüşümleri:

```text id="pa9ouh"
overall_valid → Genel Durum
valid_checks → Geçen Kontrol
errors → Hata
warnings → Uyarı
checked_at → Son kontrol
```

Validator key’leri UI’da şu şekilde gösterilmelidir:

```text id="yu8cis"
commodity_dictionary → Ürün Sözlüğü
supplier_capabilities → Tedarikçi Yetkinlik Matrisi
customer_memory → Müşteri Hafızası
hs_commodity_map → HS / GTIP Eşleştirme
```

Yeni data health validator eklendiğinde, teknik key ile birlikte kullanıcı dostu UI label’ı da eklenmelidir.

Bu kuralın amacı, operasyon ekranının geliştirici terimleri yerine anlaşılır iş diliyle çalışmasını sağlamaktır.

## RULE-075 — Data Health UI Labels Must Be Contract-Tested

MINAI Data Sağlığı Dashboard'da kullanılan validator label mapping merkezi ve test edilebilir olmalıdır.

Merkezi helper:

    src/core/data_health_labels.py
    get_data_health_check_label()

UI, kendi yerel label sözlüğünü oluşturmamalı; merkezi helper'ı kullanmalıdır.

Contract test en az şu mapping'leri doğrulamalıdır:

    commodity_dictionary → Ürün Sözlüğü
    supplier_capabilities → Tedarikçi Yetkinlik Matrisi
    customer_memory → Müşteri Hafızası
    hs_commodity_map → HS / GTIP Eşleştirme

Bilinmeyen validator anahtarları için okunabilir fallback davranışı da test edilmelidir.

Yeni data health validator eklendiğinde şu yerler birlikte güncellenmelidir:

    src/core/data_health.py
    src/core/data_health_labels.py
    evaluate_data_health_summary()
    evaluate_data_health_label_mapping()
    Data Sağlığı Dashboard
    dokümantasyon

Bu kuralın amacı, API validator anahtarları ile kullanıcıya gösterilen UI etiketleri arasındaki contract'ın sessizce bozulmasını engellemektir.

## RULE-076 — Data Health Checks Must Be Registry-Driven

MINAI’de data health check tanımları merkezi registry üzerinden yönetilmelidir.

Merkezi registry dosyası:

    src/core/data_health_registry.py

Her data health check en az şu alanlara sahip olmalıdır:

    key
    label
    validator

Data health summary, UI label mapping ve regression testleri mümkün olduğunca bu registry’den beslenmelidir.

Yeni data health validator eklendiğinde şu yerler kontrol edilmelidir:

    src/core/data_health_registry.py
    src/core/data_health.py
    src/core/data_health_labels.py
    evaluate_data_health_summary()
    evaluate_data_health_label_mapping()
    Data Sağlığı Dashboard
    docs/decision-log.md
    docs/operational-rules.md

Validator key, label ve validator fonksiyonu ayrı dosyalarda tekrar hardcoded edilmemelidir.

Bu kuralın amacı, data health sisteminde kaynak tekrarını azaltmak ve yeni validator eklerken UI, API ve test contract’larının birlikte güncel kalmasını sağlamaktır.

## RULE-077 — Data Health Registry Integrity Must Be Tested

MINAI data health registry bütünlüğü test suite içinde doğrulanmalıdır.

Registry dosyası:

    src/core/data_health_registry.py

Her registry kaydı en az şu alanları sağlamalıdır:

    key
    label
    validator

Integrity test şu durumları kontrol etmelidir:

    Registry boş olmamalıdır.
    Check key boş olmamalıdır.
    Check label boş olmamalıdır.
    Validator callable olmalıdır.
    Duplicate key olmamalıdır.
    Duplicate label olmamalıdır.
    Validator çalıştırıldığında dict dönmelidir.
    Validator sonucu valid anahtarını içermelidir.

Yeni data health validator eklendiğinde registry integrity testinin geçmesi zorunludur.

Bu kuralın amacı, data health registry'nin UI, API ve test contract'ları için güvenilir merkezi kaynak olarak kalmasını sağlamaktır.

## RULE-078 — Data Health Summary Checks Must Include Display Metadata

MINAI data health summary içindeki her check sonucu kullanıcı dostu display metadata içermelidir.

Zorunlu metadata alanı:

    label

Label değeri merkezi data health registry üzerinden alınmalıdır:

    src/core/data_health_registry.py

Her summary check sonucu en az şu yapıyı desteklemelidir:

    label
    valid
    errors
    warnings

UI, check adını gösterirken öncelikle API sonucundaki `label` alanını kullanmalıdır.

API sonucunda label bulunmaması durumunda merkezi label helper fallback olarak kullanılabilir:

    get_data_health_check_label()

Label metadata'sı registry'deki tanımla eşleşmelidir.

Yeni validator eklendiğinde şu kontroller yapılmalıdır:

    Registry kaydında kullanıcı dostu label var mı?
    Summary sonucu label metadata'sını içeriyor mu?
    UI API label bilgisini gösterebiliyor mu?
    evaluate_data_health_summary_check_metadata() testi geçiyor mu?
    Data health summary contract dokümantasyonu güncel mi?

Bu kuralın amacı, teknik validator anahtarları ile kullanıcıya gösterilen adlar arasındaki ilişkiyi API seviyesinde açık ve güvenilir hale getirmektir.


## RULE-079 — ADR Status and Class Must Be Deterministic and Complete

MINAI, ADR durumunu yalnızca AI çıkarımına dayanarak belirlememelidir.

Ham email metni ADR statüsü için deterministik safety override olarak kullanılmalıdır.

Email açıkça ADR ifadesi içeriyorsa:

    is_adr = true

ADR sınıfı belirtilmişse:

    adr_class = belirtilen sınıf

ADR belirtilmiş ancak ADR sınıfı eksikse:

    adr class kritik eksik bilgi olarak işaretlenmelidir
    fiyat ve teklif akışı durmalıdır
    clarification email hazırlanmalıdır
    ekipman kararı ADR Equipment Review olmalıdır
    operational consistency hata üretmelidir

Email ADR olmadığını açıkça belirtiyorsa:

    is_adr = false
    adr_class = null

Negation örnekleri:

    non-ADR
    ADR değil
    ADR değildir
    ADR kapsamında değildir
    ADR kapsamı dışında
    not subject to ADR

Email içinde ADR ifadesi yoksa AI tarafından varsayılan ADR bilgisi korunmamalıdır.

ADR sınıfı eksikken standart Tenteli, Reefer veya başka nihai ekipman seçimi yapılmamalıdır.

Clarification email en az şu bilgiyi istemelidir:

    Yükün ADR sınıfı ve varsa alt sınıfı

Yeni ADR parser veya regex değişikliklerinde şu regression testleri korunmalıdır:

    ADR Class 7
    ADR class missing
    Non-ADR negation

Bu kuralın amacı, ADR yüklerinde yanlış sınıflandırma, yanlış ekipman ve erken fiyatlandırma riskini önlemektir.

## RULE-080 — ADR Loads Require ADR-Capable Equipment and Suppliers

ADR olarak belirlenmiş bir yükte standart ekipman ve ADR yetkinliği doğrulanmamış taşıyıcı kullanılmamalıdır.

Ekipman kararı:

    ADR sınıfı eksik:
    ADR Equipment Review

    ADR Class 1 veya 7:
    Special ADR Equipment

    Diğer bilinen ADR sınıfları:
    ADR-Capable Equipment

ADR yüklerinde seçilebilecek supplier:

    special_capabilities listesinde adr yetkinliği bulunmalıdır

ADR yetkinliği bulunmayan supplier adayları seçim aşamasında elenmelidir.

Operational consistency, seçilmiş supplier için ADR yetkinliğini bağımsız olarak doğrulamalıdır.

ADR sınıfı ve ADR statüsü zaten açıkça biliniyorsa müşteriden tekrar ADR statüsü istenmemelidir.

Class 1 ve 7 için mevcut red risk ve management review kuralları korunmalıdır.

Regression testleri en az şu senaryoları kapsamalıdır:

    ADR Class 7
    ADR class missing
    Non-ADR negation
    ADR Class 3 standard

## RULE-081 — High-Risk ADR Classes Require Class-Specific Supplier Capability

ADR Class 1 ve ADR Class 7 yüklerinde genel ADR yetkinliği tek başına yeterli değildir.

Supplier capability gereksinimleri:

    ADR Class 1:
    special_capabilities içinde adr ve class_1 bulunmalıdır

    ADR Class 7:
    special_capabilities içinde adr ve class_7 bulunmalıdır

    Diğer ADR sınıfları:
    special_capabilities içinde adr bulunması yeterlidir

Gerekli sınıf yetkinliği bulunmayan supplier seçim aşamasında elenmelidir.

Operational consistency, seçilmiş supplier için aynı sınıf bazlı yetkinliği bağımsız olarak doğrulamalıdır.

Regression testleri şu ayrımı korumalıdır:

    Class 7 → genel ADR supplier elenir
    Class 3 → genel ADR supplier seçilebilir

Bu kuralın amacı, yüksek riskli ADR sınıflarında genel ADR yetkinliğinin yanlışlıkla yeterli kabul edilmesini önlemektir.

## RULE-082 — ADR Capability Data Must Be Internally Consistent

Supplier capability datasında ADR bilgileri kendi içinde tutarlı olmalıdır.

Zorunlu kurallar:

    class_1 varsa adr da bulunmalıdır
    class_7 varsa adr da bulunmalıdır

    Special ADR Equipment varsa adr bulunmalıdır
    ADR-Capable Equipment varsa adr bulunmalıdır

Aynı special_capability bir supplier profilinde birden fazla kez bulunmamalıdır.

Sistem tarafından tanınmayan special_capability isimleri validation hatası üretmelidir.

ADR capability validation, supplier capability data health kontrolünün bir parçası olmalıdır.

Regression testi en az şu hataları doğrulamalıdır:

    duplicate capability
    unknown capability
    class-specific capability without adr
    ADR equipment without adr

## RULE-083 — Supplier Capability Names Must Come From the Central Registry

Supplier capability isimleri farklı modüllerde serbest string olarak tekrar edilmemelidir.

Aşağıdaki modüller merkezi capability registry kullanmalıdır:

    supplier capability validator
    supplier selection
    operational consistency

İzin verilen capability isimleri:

    adr
    class_1
    class_7
    reefer
    temperature_controlled
    cold_chain
    ltl
    partial
    parsiyel

Yüksek riskli ADR sınıf capability mapping'i merkezi olarak tanımlanmalıdır:

    ADR Class 1 -> class_1
    ADR Class 7 -> class_7

Yeni capability eklenirken önce merkezi registry güncellenmelidir.

Validator, selection ve consistency aynı capability adını registry üzerinden kullanmalıdır.

## RULE-084 — Supplier Capability Registry Must Be Data-Driven and Validated

Supplier capability isimleri ve ADR class capability mapping'leri merkezi veri dosyasından yönetilmelidir.

Kaynak:

    data/supplier_capability_registry.json

Registry en az şu alanları içermelidir:

    allowed_special_capabilities
    adr_class_capability_map

ADR class mapping'de kullanılan capability, allowed_special_capabilities listesinde bulunmalıdır.

Duplicate capability isimleri validation hatası üretmelidir.

Registry içinde genel adr capability bulunmalıdır.

Registry validator, Data Health sistemine bağlı olmalıdır.

Supplier selection, operational consistency ve supplier capability validator aynı data-driven registry'yi kullanmalıdır.

Regression testi en az şu hataları doğrulamalıdır:

    duplicate allowed capability
    unsupported ADR class mapping target

## RULE-085 — Supplier Capability Registry Must Fail Fast With Controlled Errors

Supplier capability registry runtime sırasında yüklenemiyorsa sistem sessiz fallback ile devam etmemelidir.

Aşağıdaki durumlar kontrollü runtime error üretmelidir:

    registry file missing
    invalid JSON
    registry root is not an object

Bu hatalar ortak exception tipi üzerinden raporlanmalıdır:

    SupplierCapabilityRegistryError

Runtime loader test edilebilir olmalıdır ve alternatif path kabul etmelidir.

Registry runtime integrity regression testi en az şu senaryoları kapsamalıdır:

    missing file
    invalid JSON
    non-object root

Registry yükleme durumu metadata olarak erişilebilir olmalıdır.

Fail-fast davranışının amacı, capability registry bozukken sistemin yanlış supplier veya equipment kararı üretmesini önlemektir.

## RULE-086 — Quote Readiness Decisions Must Follow a Single Priority Order

Fiyat/teklif hazırlığı kararı tek bir merkezi karar motoru tarafından verilmelidir.

Karar önceliği:

    1. RED risk -> management_review
    2. Kritik eksik bilgi -> clarification
    3. Kalan operational consistency error -> blocked
    4. Yellow risk -> quote_with_review
    5. Temiz akış -> quote_ready

Operational consistency error her durumda otomatik olarak blocked sonucu üretmemelidir.

Eksik bilgiyle açıklanabilen consistency hatalarında clarification öncelikli olmalıdır.

RED risk, diğer quote readiness durumlarından önce management review gerektirmelidir.

Blocked durumda:

    quote oluşturulmamalıdır
    insan kontrolü zorunlu olmalıdır
    hata nedenleri readiness sonucunda görünmelidir

Pipeline, action recommendation ve test sistemi aynı quote readiness sonucunu kullanmalıdır.

## RULE-087 — Supplier RFQ Responses Must Be Validated Before Use

Supplier RFQ cevapları fiyat seçimi, lifecycle synchronization veya müşteri teklifi üretiminde kullanılmadan önce ilgili RFQ taslağıyla doğrulanmalıdır.

Zorunlu eşleşmeler:

    response.rfq_id == draft.rfq_id
    response.supplier_name == draft.supplier_name
    response.rfq_priority == draft.priority

Geçersiz cevap nedenleri kontrollü olarak raporlanmalıdır:

    unknown_rfq_id
    supplier_name_mismatch
    priority_mismatch

Ham cevaplar denetim amacıyla korunabilir; ancak yalnızca doğrulanmış cevaplar fiyat seçiminde kullanılmalıdır.

Geçersiz supplier cevabı hiçbir koşulda müşteri teklifine dönüşmemelidir.

---

## RULE-088 — Supplier Response Status and Price Data Must Be Consistent

`quoted` durumundaki supplier cevabı pozitif bir maliyet içermelidir.

Zorunlu kural:

    status = quoted
    cost > 0

Aşağıdaki durumlarda `cost` bulunmamalıdır:

    no_capacity
    declined
    needs_clarification

Kullanılabilir supplier fiyatı bulunmuyorsa sistem fallback veya tahmini fiyat üretmemelidir.

Bu durumda workflow sonucu:

    supplier_response_required

olmalıdır.

---

## RULE-089 — Supplier RFQ Lifecycle Must Use Only Valid Responses

RFQ taslağı yalnızca doğrulanmış supplier cevabı bulunduğunda:

    status = responded

durumuna geçmelidir.

`responded_at`, aynı RFQ için mevcut geçerli cevaplar arasındaki en güncel:

    received_at

değerinden türetilmelidir.

Bilinmeyen RFQ kimliği, yanlış supplier veya yanlış priority içeren cevap RFQ lifecycle durumunu değiştirmemelidir.

---

## RULE-090 — Supplier Quote Selection Must Be Multi-Criteria and Traceable

Supplier teklif seçimi yalnızca en düşük fiyat veya ilk RFQ önceliğine göre yapılmamalıdır.

Mevcut v1 seçim ağırlıkları:

    supplier_score      %70
    actual_price_score  %20
    transit_score       %10

Aynı para birimindeki en düşük teklif:

    actual_price_score = 1.0

almalıdır.

Diğer teklifler:

    minimum_cost / offered_cost

oranıyla puanlanmalıdır.

Transit süresi okunamıyorsa sistem sahte kesinlik üretmemeli ve nötr skor kullanmalıdır:

    transit_score = 0.5

Seçim sırası:

    1. En yüksek total_score
    2. Eşitlikte daha düşük RFQ priority
    3. Hâlâ eşitse daha düşük maliyet

Seçim sonucu en az şu bilgileri taşımalıdır:

    selected_supplier
    selected_rfq_id
    selected_total_score
    selection_reason
    price_difference
    score_difference
    rejected_alternatives

---

## RULE-091 — Supplier RFQ Repository Must Preserve Lifecycle State

RFQ taslakları ve cevapları repository sınırı üzerinden saklanmalıdır.

Workflow sırası:

    1. Taslakları oluştur
    2. Taslakları repository’ye kaydet
    3. Supplier cevaplarını al
    4. Cevapları repository’ye kaydet
    5. Cevapları doğrula
    6. Lifecycle durumunu senkronize et
    7. Güncel taslakları tekrar kaydet

Aynı `rfq_id` ile kaydedilen taslak mevcut kaydı güncellemelidir.

Repository’den dönen liste üzerinde yapılan dış değişiklik repository iç durumunu değiştirmemelidir.

Storage teknolojisi pipeline içine gömülmemeli; repository sözleşmesi üzerinden değiştirilmelidir.

---

## RULE-092 — Identical Supplier Responses Must Not Be Stored Twice

Aynı supplier cevabının birebir tekrar kaydedilmesi engellenmelidir.

Duplicate kontrolü en az şu alanları dikkate almalıdır:

    rfq_id
    supplier_name
    rfq_priority
    status
    cost
    currency
    transit_time
    validity_date
    equipment_type
    notes
    source
    received_at

Aynı cevap yeniden gelirse repository kayıt sayısı artmamalıdır.

Aşağıdaki değişikliklerden biri varsa cevap yeni revision olarak korunmalıdır:

    cost değişikliği
    status değişikliği
    notes değişikliği
    yeni received_at
    diğer ticari veya operasyonel alan değişiklikleri

---

## RULE-093 — Every Customer Quote Must Start With Pending Human Approval

Başarılı teklif workflow’u hiçbir zaman önceden onaylanmış kayıt üretmemelidir.

Yeni teklif onay durumu:

    pending

olmalıdır.

Teklif üretilemeyen branch’lerde:

    quote_approval = None

olmalıdır.

Approved onay için zorunlu alanlar:

    approved_by
    approved_at

Rejected onay için zorunlu alan:

    rejection_reason

Pending veya invalidated onay, approval metadata taşımamalıdır.

---

## RULE-094 — Quote Approval Must Be Bound to an Exact Snapshot

İnsan onayı belirli bir teklif snapshot’ına bağlı olmalıdır.

Snapshot en az şu alanları içermelidir:

    supplier_name
    supplier_cost
    final_price
    currency
    transit_time
    quote_subject
    quote_body

Aşağıdaki alanlardan herhangi biri değişirse önceki onay geçerli sayılmamalıdır:

    seçilen supplier
    supplier cost
    customer final price
    currency
    transit time
    email subject
    email body

Onay yalnızca:

    approval_status = approved

ve snapshot güncel teklif ile birebir eşleşiyorsa geçerlidir.

---

## RULE-095 — Quote Sending Must Fail Closed

Teklif gönderim kararı merkezi güvenlik servisi tarafından verilmelidir.

Gönderimi bloklayan durumlar:

    approval_missing
    approval_pending
    approval_rejected
    approval_invalidated
    quote_snapshot_mismatch

Yalnızca şu koşullar birlikte sağlanırsa:

    approval_status = approved
    approval snapshot güncel teklif ile eşleşiyor

`can_send = true` sonucu üretilebilir.

Belirsizlik, eksik onay veya snapshot uyuşmazlığında sistem gönderime izin vermemelidir.

---

## RULE-096 — Send Preparation Must Not Perform Real Delivery

`prepare_quote_for_sending(...)` servisi gerçek e-posta gönderimi yapmamalıdır.

İzin verilen sonuçlar:

    blocked
    send_ready

Bu aşamada her iki durumda da:

    sent = false

olmalıdır.

`send_ready`, yalnızca güvenlik kontrollerinin geçtiğini ifade eder; teslimatın gerçekleştiğini ifade etmez.

Boş recipient email reddedilmelidir.

API endpoint’i:

    POST /quotes/prepare-send

gerçek email provider veya SMTP adapter çağırmamalıdır.

Gerçek gönderim, ayrı adapter ve idempotency kuralları tamamlanmadan etkinleştirilmemelidir.

## RULE-097 — Quote Approval Records Must Be Loaded From a Server-Side Repository

Quote approval durumu istemciden gönderilen tam bir approval nesnesine güvenilerek kullanılmamalıdır.

Approval işlemleri şu kimlik üzerinden yapılmalıdır:

    approval_id

Sistem approval kaydını sunucu tarafındaki:

    QuoteApprovalRepository

üzerinden yüklemelidir.

Bilinmeyen `approval_id` kontrollü olarak reddedilmelidir:

    HTTP 404

Başarılı quote workflow’u oluşturduğu pending approval kaydını repository’ye yazmalıdır.

Teklif oluşturulmayan early-stop workflow branch’leri approval kaydı oluşturmamalıdır.

Mevcut InMemory repository uygulama yeniden başlatıldığında kayıtları kaybeder. Bu davranış kalıcı storage olarak kabul edilmemelidir.

---

## RULE-098 — Quote Approval Transitions Must Follow a Controlled Lifecycle

Approval durum değişiklikleri merkezi servis üzerinden yapılmalıdır.

İzin verilen geçişler:

    pending -> approved
    pending -> rejected
    pending -> invalidated
    approved -> invalidated

Aşağıdaki durumlar terminal kabul edilmelidir:

    rejected
    invalidated

Approved kayıt tekrar approved veya rejected durumuna geçirilemez.

Geçersiz lifecycle geçişleri:

    HTTP 409

ile reddedilmelidir.

Approved durumda:

    approved_by
    approved_at

zorunludur.

Rejected durumda:

    rejection_reason

zorunludur.

Boş `approved_by` veya `rejection_reason`:

    HTTP 422

ile reddedilmelidir.

Invalidated duruma geçerken approval ve rejection metadata temizlenmelidir.

---

## RULE-099 — Prepare-Send Must Trust Approval Identity, Not Client Approval State

`POST /quotes/prepare-send` istemciden tam `QuoteApproval` nesnesi kabul etmemelidir.

Request yalnızca approval kimliğini taşımalıdır:

    approval_id

Gönderim hazırlığı approval kaydını server-side repository’den yüklemelidir.

İstemcinin request içinde oluşturduğu veya değiştirdiği approval status gönderim yetkisi vermemelidir.

Repository’den yüklenen approval için mevcut send safety kuralları uygulanmalıdır:

    approval_status = approved
    approval snapshot güncel teklif ile eşleşiyor

Unknown approval:

    HTTP 404

Boş recipient email:

    HTTP 422

Başarılı güvenlik kontrolü yalnızca:

    send_ready
    sent = false

sonucu üretmelidir.

Gerçek email delivery bu endpoint’in sorumluluğu değildir.

## RULE-100 — Quote Workflow Data Must Be Grouped Under a Quote Case

Başarılı müşteri teklif çalışmasında birbirine ait veriler tek Quote Case altında gruplanmalıdır.

Quote Case en az şu alanları taşımalıdır:

    case_id
    shipment
    supplier_quote_selection_decision
    supplier_quote
    customer_quote
    quote_draft
    quote_approval
    quote_send_safety

Bu alanlar farklı ve ilişkisiz geçici kayıtlar gibi ele alınmamalıdır.

Aynı teklif çalışmasına ait veriler aynı `case_id` altında tutulmalıdır.

Quote Case mevcut MVP kapsamında teklif çalışma dosyasıdır.

Booking, aktif taşıma takibi veya faturalama kaydı olarak kabul edilmemelidir.

---

## RULE-101 — Quote Case Persistence Must Use a Repository Boundary

Quote Case saklama davranışı pipeline içine doğrudan gömülmemelidir.

Workflow:

    QuoteCaseRepository

sözleşmesi üzerinden case kaydetmeli ve okumalıdır.

İlk implementation:

    InMemoryQuoteCaseRepository

olabilir.

Aynı `case_id` ile kaydedilen case mevcut kaydı güncellemelidir.

Unknown `case_id` repository seviyesinde:

    None

döndürmelidir.

Repository'den dönen liste üzerinde yapılan dış değişiklik repository iç durumunu değiştirmemelidir.

---

## RULE-102 — Only Successful Quote Workflows May Persist Quote Cases

Quote Case yalnızca gerçek bir müşteri quote akışı başarıyla oluştuğunda kaydedilmelidir.

Başarılı workflow en az şu bileşenleri üretebilir:

    supplier_quote
    customer_quote
    quote_draft
    quote_approval
    quote_send_safety

Early-stop workflow durumlarında:

    quote_case = None

olmalıdır.

Örnek early-stop durumları:

    clarification
    management_review
    blocked
    supplier_response_required

Bu branch'ler tamamlanmış teklif çalışma dosyası olarak persist edilmemelidir.

---

## RULE-103 — Quote Case Must Be Retrievable by Stable Case Identity

Her Quote Case stabil bir:

    case_id

taşımalıdır.

API aynı uygulama süreci içinde oluşturulan Quote Case'i şu endpoint üzerinden geri çağırabilmelidir:

    GET /quote-cases/{case_id}

Bilinmeyen case:

    HTTP 404

üretmelidir.

Liste endpoint'i:

    GET /quote-cases

mevcut repository kayıtlarını döndürmelidir.

Quote Case yeniden yüklenirken en az şu bilgiler korunmalıdır:

    quote_approval
    quote_send_safety
    supplier_quote
    customer_quote
    quote_draft

---

## RULE-104 — Quote Case API Tests Must Not Depend on Non-Deterministic AI Parsing

Quote Case API regression testleri gerçek AI parser davranışına bağlı olmamalıdır.

Test sırasında parser kontrollü ve deterministik bir Shipment döndürmelidir.

Amaç:

    API persistence contract
    serialization
    list/get behavior
    HTTP error behavior

testlerinin model veya parser varyasyonundan etkilenmesini önlemektir.

AI parser kalitesi ayrı regression testlerinde doğrulanmalıdır.

Quote Case API contract testi yalnızca Quote Case API davranışını test etmelidir.

---

## RULE-105 — Customer Price Uses Cost Markup Terminology

Varsayılan customer price formülü:

    supplier cost × 1.15

olduğu için bu oran gross margin değil, cost üzerine yüzde 15 markup'tır.
Customer Quote alanları `markup_type` ve `markup_value` adlarını kullanmalıdır.
Eski `margin_type` ve `margin_value` input adları geçiş uyumluluğu için kabul
edilebilir ancak yeni serialized output'ta kullanılmamalıdır.

Nihai fiyat yukarı yönde en yakın 10 EUR sınırına yuvarlanır. Zaten 10 EUR
sınırında olan fiyat değişmez; cent değerleri yuvarlama öncesinde kesilmez.

---

## RULE-106 — Quote Case Retrieval Must Use Current Approval State

Quote approval için authoritative current state `QuoteApprovalRepository` kaydıdır.
Quote Case içinde oluşturma anından kalan approval ve send-safety snapshot'ı,
sonraki lifecycle geçişlerinin current truth'u olarak sunulmamalıdır.

`GET /quote-cases` ve `GET /quote-cases/{case_id}` response'ları approval'ı
repository'den yeniden yüklemeli ve send safety kararını bu current approval ile
yeniden hesaplamalıdır. Bu kural approved, rejected ve invalidated durumlarına
aynı şekilde uygulanır.

---

## RULE-107 — Commodity Clarification Questions Must Be Resolvable

Commodity profile kaynaklı her clarification requirement tek bir executable
tanım taşımalıdır:

    key
    value_type
    question
    critical

Canonical tanım `data/commodity_dictionary.json` içindeki
`operational_profile.clarification_requirements` alanıdır. Ayrı
`missing_info_fields` ve `critical_missing_info_fields` listeleri data içinde
tekrar tutulmamalı; gerekiyorsa mevcut output uyumluluğu için bu tanımlardan
türetilmelidir.

Müşteri emailinde açıkça bulunan cevaplar AI extraction tarafından Shipment
`commodity_attributes` alanına canonical key ile yazılır. Bilgi verilmemişse key
bulunmaz. Açık bir `false` / hayır cevabı key mevcut ve value `false` olacak
şekilde saklanır; eksik bilgi sayılmaz.

Clarification cevapları mevcut Shipment'a uygulanırken:

* key tanımlı ve shipment commodity'si için geçerli olmalıdır,
* value canonical `value_type` ile eşleşmelidir,
* uygulama tüm cevaplar doğrulandıktan sonra atomik olarak yeni Shipment kopyasına yapılmalıdır,
* bilinmeyen key arbitrary Shipment alanı oluşturmamalı ve kontrollü hata vermelidir,
* missing-info yeniden çalıştırıldığında yalnızca cevapsız requirement'lar eksik kalmalıdır.

Bu domain kontratı email reply ingestion veya persistence anlamına gelmez.

---

## RULE-108 — Mandatory Document Exceptions Require Explicit Human Approval

Bir clarification cevabının bulunması, yükün otomatik olarak teklif verilebilir
olduğu anlamına gelmez. Canonical clarification requirement üzerinde
`compliance_policy.required_before_quote=true` tanımlanmışsa aşağıdaki durumlar
ayrı tutulmalıdır:

    cevap yok
    -> clarification

    belge mevcut (true)
    -> requirement karşılandı; diğer normal kontroller devam eder

    belge mevcut değil (false), istisna talebi yok
    -> regulatory_blocked

    belge mevcut değil (false), müşteri daha sonra sağlayacağını söylüyor
    -> regulatory_review

    regulatory review approved
    -> sonraki normal kontroller devam eder

    regulatory review rejected
    -> regulatory_blocked

Müşterinin zorunlu belgeyi daha sonra sağlayacağına dair taahhüdü, MINAI'nin
otonom olarak devam etmesi için yetki değildir. Açık insan onayı bulunmadığında
akış fail-closed kalmalı; otomatik müşteri teklifi, nihai teklif veya gönderim
uygunluğu üretmemelidir.

Bu politika document-name-specific kodla değil, commodity dictionary içindeki
canonical `compliance_policy` metadata'sı ile çalışmalıdır. Bir belgenin adı,
clarification içinde kritik olması veya descriptive metinde mevzuat/uygunluk
kontrolüyle ilişkilendirilmesi tek başına regulatory blocking sınıflandırması
değildir. Blokaj ancak canonical requirement verisinde doğrulanmış ve açık bir
`compliance_policy` bulunduğunda etkinleşir.

Mevcut MSDS/SDS, medikal uygunluk ve pharma uygunluk/ruhsat requirement'larının
hangi ürün, rota veya ülke kombinasyonunda hukuken zorunlu olduğu henüz
doğrulanmamıştır. Bu alanlar mevcut commodity kurallarına göre clarification veya
risk/human-review davranışını sürdürebilir; ancak doğrulanmış metadata eklenene
kadar negatif cevapları otomatik regulatory prohibition sayılmamalıdır.

---

## RULE-109 — Supplier RFQ Generation Is Not Supplier RFQ Sending

Supplier RFQ lifecycle aşağıdaki insan kontrollü geçişleri izlemelidir:

    draft
    -> approved
    -> awaiting_response
    -> responded

**RFQ generation is not RFQ sending.** Otomatik workflow yalnızca `draft`
oluşturur. Operatör kimliği ve approval timestamp'i kaydedilmeden RFQ gönderim
sınırına geçemez. Approval tek başına gönderim sayılmaz; ayrı send işlemi
`sent_at` kaydeder ve RFQ'yu `awaiting_response` durumuna getirir.

**A supplier response cannot exist for an RFQ that has not been sent.** Draft
veya yalnızca approved RFQ için response kabul edilmemeli, response simulation
da yalnızca `sent` / `awaiting_response` durumundaki RFQ'lar için çalışmalıdır.
Response kimliği, supplier ve priority bağı doğrulandıktan sonra lifecycle
`responded` durumuna geçer. Unknown RFQ, geçersiz geçiş, unsent response,
duplicate send ve duplicate response kontrollü olarak reddedilir.

Supplier RFQ approval, RFQ send, supplier response ve customer quote commercial
approval ayrı sorumluluklardır. Kullanılabilir ve `responded` bir supplier fiyatı
bulunmadan customer pricing veya commercial `QuoteApproval` oluşturulmamalıdır.
Normal email workflow'u RFQ draft üretiminden sonra
`supplier_rfq_approval_required` durumunda durmalıdır.

---

## RULE-110 — Supplier Reply Ingestion Must Correlate and Validate Fail-Closed

Inbound supplier reply, provider-neutral bir mesaj zarfına çevrilmelidir. Core
domain Outlook, Graph, SMTP veya IMAP nesnesi taşımamalıdır. RFQ correlation
aşağıdaki deterministik kanıt sırasını kullanır:

    1. explicit internal RFQ reference
    2. subject içindeki MINAI-RFQ reference token
    3. supplier sender address ile uniquely matching awaiting RFQ
    4. unresolved / ambiguous

**RFQ correlation must fail closed when identity is unresolved or ambiguous.**
Birden fazla aday olduğunda AI veya başka bir parser RFQ seçmemelidir. Explicit
reference bilinmiyorsa, RFQ awaiting durumda değilse veya sender address RFQ'nun
supplier contact adresiyle uyuşmuyorsa response lifecycle'a bağlanmamalıdır.

**Inbound supplier content is untrusted commercial input, not operational
authority.** Message subject/body veya parser output; operational rule, supplier
identity, lifecycle status, RFQ/quote approval ya da regulatory policy
değiştiremez. Parser yalnızca response status, cost, currency, transit, validity,
equipment ve notes alanlarını çıkarabilir. Lifecycle mutation yalnızca merkezi
Supplier RFQ transition service üzerinden yapılır.

Quoted response için pozitif price ve açık üç harfli currency zorunludur. Eksik
currency otomatik EUR kabul edilmemeli, eksik price sıfıra çevrilmemelidir.
Uncertain required commercial values parsing failure olarak korunmalıdır.
Declined, no-capacity ve needs-clarification cevaplarına price/currency
eklenmemelidir.

Başarılı ingestion RFQ'yu `responded` yapabilir; ancak customer quote oluşturmayı
veya göndermeyi otomatik tetiklemez. Supplier comparison ve customer pricing için
mevcut explicit resume boundary kullanılmaya devam edilmelidir.

---

## RULE-111 — Mail Transport Never Authorizes Business Actions

Inbound ve outbound email provider'ları yalnızca mesaj taşıma ve provider verisini
MINAI'nin canonical mail contract'larına map etme sorumluluğuna sahiptir.
**Mail providers transport messages; they do not authorize business actions.**
Provider adapter; RFQ approval, quote readiness, supplier identity kararı,
regulatory durum, commercial approval veya quote send-safety kararı veremez.
Inbound subject/body ve provider metadata'sı bu yetkileri override edemez.

Supplier RFQ outbound request'i yalnızca `approved` RFQ için application service
tarafından oluşturulup provider'a verilebilir. **Lifecycle advancement after
outbound email requires confirmed provider send success.** Provider `sent`
sonucu, aynı outbound operation identity'si, provider message identity ve send
timestamp'i taşımadan RFQ `awaiting_response` durumuna geçmemelidir. Failed veya
provider-unavailable sonuçlarında RFQ `approved` kalmalı ve güvenli retry mümkün
olmalıdır. Draft, already-sent ve diğer geçersiz state'ler provider çağrısından
önce reddedilmelidir.

Customer quote provider'a ancak mevcut commercial `QuoteApproval` geçerli ve
quote send-safety olumluysa ulaşabilir. Clarification email'i provider-neutral
outbound request olarak hazırlanabilir; hazırlanması gönderim değildir ve mevcut
human-controlled policy'yi değiştirmez.

Outbound operation identity idempotency sınırıdır. Aynı RFQ ikinci kez lifecycle
ilerlemesi veya ikinci provider çağrısı üretmemelidir. Inbound external message
identity deduplication davranışı provider ve mailbox namespace'i ile korunur.

---

## RULE-112 — AI Shipment Extraction Requires Human Confirmation

**AI-extracted shipment facts are proposals until explicitly confirmed by a
human operator.** Yeni customer inquiry ilk çağrıda yalnızca normalize edilmiş
inbound mail zarfını ve `ShipmentProposalSnapshot` içeren bir extraction proposal
oluşturmalıdır. Bu proposal aşağıdaki motorlara girdi olamaz:

    customer memory
    missing information / regulatory compliance
    equipment / risk
    supplier selection
    quote readiness
    RFQ generation
    customer pricing

`/process-email` bu nedenle `extraction_confirmation_required` durumunda
durmalıdır. **Only a confirmed shipment snapshot may acquire operational
authority.** İnsan operatör proposal'ı değişmeden teyit edebilir veya kontrollü
shipment field corrections sağlayabilir. Düzeltmeler atomik doğrulanmalı;
bilinmeyen field, invalid value veya unresolved safety fact mevcut proposal'ı
kısmen değiştirmemelidir.

İlk AI snapshot'ı teyit sırasında mutate edilmemelidir. Proposal en az aşağıdaki
kanıtları birlikte korumalıdır:

    original normalized inbound mail
    first AI shipment proposal
    confirmed shipment snapshot
    changed fields and normalized corrections
    claimed operator identity
    confirmation timestamp

`is_adr`, `is_temperature_controlled` ve `is_high_value` alanlarında `null`
"emailde belirtilmedi / unknown" anlamına gelir; `false` ile aynı değildir.
Operational `Shipment` oluşturmadan önce bu alanlar insan tarafından explicit
`true` veya `false` olarak çözülmelidir. Duplicate confirmation ve unknown
proposal fail-closed olmalıdır. Confirmed snapshot mevcut clarification,
regulatory, RFQ ve send-safety kapılarını bypass etmez.

Bu aşamadaki operator identity yalnızca claimed audit metadata'sıdır;
authentication veya authorization kanıtı değildir.


---

## RULE-113 — Customer Memory Requires Trusted Identity Evidence

Customer memory enrichment must not use arbitrary raw email text, quoted history,
forwarded content, or signatures as customer identity evidence.

The human-confirmed `Shipment.customer_name` may identify a candidate profile, but
automatic memory enrichment requires the inbound sender to match an explicitly
trusted sender address or trusted sender domain on that customer profile.

If a candidate profile exists but sender identity is not trusted, the result must
remain `sender_verification_required` and no customer defaults, addresses,
equipment preferences, sensitivity settings, or operational notes may be injected.

Absence of sender metadata must fail closed. Raw text substring matching is not an
identity mechanism.

Sender/domain trust data is operational configuration, not authentication. Full
operator authentication and authorization remain a separate P0 control.


---

## RULE-114 — Pilot Workflow State Must Survive Process Restart

Controlled shadow-pilot workflow state and evidence must not depend on Python process memory.

Extraction proposals, supplier RFQ drafts/workflows/responses, inbound supplier message deduplication keys, quote approvals, and quote cases must be stored in a durable repository that survives application restart.

Every durable repository save must also create an append-only pilot evidence event containing at least a process `run_id`, event type, entity type, entity ID, validated snapshot payload, and timestamp. Current-state records may be updated; historical pilot events must not be overwritten by normal repository operations.

A restart must not make a previously ingested supplier message or supplier response eligible to be accepted as new merely because in-memory state was lost.

The pilot database is evidence infrastructure, not authorization. Its existence does not permit real company data use before privacy, isolation, retention, and access controls are separately approved.

---

## RULE-115 — Raw Inbound Mail Must Not Cross the Pilot Privacy Boundary

Raw customer email bodies must not be passed directly to the AI parser and must
not be written to MINAI pilot durable state or audit evidence.

Before parsing or persistence, inbound mail must be transformed by the approved
privacy minimizer. The stored message must carry a privacy-transform marker,
transform version, and SHA-256 fingerprint of the original body.

The privacy transform must preserve freight-operational facts required for safe
quotation while removing unnecessary personal contact/signature data where the
deterministic rules can identify it.

The canonical sender address is an explicit exception because trusted-sender
customer identity verification depends on it. Sender display names are not
required for that control and must not be persisted in the transformed envelope.

AI parser entry points must fail closed when given content that has not crossed
the privacy boundary.

Pilot durable data must be subject to an enforced retention period; default
retention is 30 days. Expired state and evidence must be deletable without
requiring application code changes.

Passing this rule does not authorize real-data shadow piloting until the remaining
deployment privacy, authentication, isolation, provenance, and legal/contractual
requirements are complete.


---

## RULE-116 — Shadow Pilot Requests Require Named Authentication and Route Isolation

When `MINAI_PILOT_MODE` is enabled, operational requests must originate from an
approved private/loopback network and, except for health checks, authenticate
with a bearer token uniquely assigned to a named pilot operator.

Pilot mode must fail closed if operator tokens, allowed networks, or the declared
bind host are missing or invalid.

The authenticated operator identity is authoritative for human confirmation and
approval evidence. User-supplied body fields must not allow an operator to claim
another person's identity.

Only explicitly approved shadow-pilot routes may be reachable. Test execution,
simulation, supplier outbound send, automated supplier-response ingestion,
customer-memory mutation/import/restore, quote-send preparation, and other
administrative or non-pilot routes must remain disabled.

Pilot network configuration may contain only private or loopback CIDRs. The
default network boundary is localhost only. A VPN/private subnet must be added
explicitly.

This rule provides a pre-MVP single-tenant access boundary and does not replace
production SSO, RBAC, tenant isolation, or infrastructure firewall controls.


---

## RULE-117 — Pilot Operational Data Must Be Provenance-Verified

Shadow-pilot operational master data must not be consumed merely because it is
present in the repository or marked active.

A dataset used to select suppliers, enrich customer operational facts, or drive
another operational pilot decision must be classified appropriately in the data
provenance registry.

Operational pilot data is usable only when all of the following are true:

1. classification is `pilot_verified`;
2. `pilot_usable` is true;
3. the verifying person is recorded;
4. the verification time is recorded;
5. the recorded SHA-256 fingerprint matches the current dataset bytes exactly.

If the fingerprint differs, provenance is considered stale and the pilot must
fail closed for required operational data.

Demo data remains permitted for development and regression testing but must not
be treated as real pilot master data. Internal reference datasets must not be
presented as authoritative external regulatory or customs sources.


---

## RULE-118 — Provenance Failures Must Be Durable and Retry-Safe

A provenance failure at an operational resume boundary must return
`data_provenance_blocked`, persist the blocked attempt, and create no new RFQ,
supplier-selection, customer-quote, approval, or quote-case artifact.

The blocked attempt must not be recorded as successful completion and must remain
retryable after the provenance registry or verified dataset is repaired. Every
retry must perform provenance verification again; a prior blocked record is not
authorization to bypass the check.

Only provenance-blocked attempts may be restarted. An attempt already in progress
or completed must fail its transition so repeated requests cannot duplicate
downstream artifacts. Operational API results must use a stable safe reason and
must not expose registry paths, raw exception details, stack traces, or message
contents.


---

## RULE-119 — Pilot-Critical Multi-Record Writes Must Commit Atomically

When one pilot business transition writes multiple related SQLite records, all
state records and their evidence events must commit in one transaction or all
must roll back.

This rule applies to RFQ workflow-and-draft creation, supplier response and RFQ
lifecycle acceptance, inbound-message deduplication for that acceptance, and
quote approval/case/progression creation. It also applies when confirmed
extraction resume creates an RFQ workflow and records completion. A failed
transition must remain safely retryable and must not leave orphan drafts,
accepted responses with stale RFQ state, orphan approvals or cases, or a falsely
completed workflow.

Transactions must contain only final durable writes after business computation
and validation. AI calls, network requests, and external outbound operations must
not execute inside the SQLite transaction. Participating SQLite repositories
must share one `SQLitePilotStore`; repository methods must not commit an outer
transaction independently.

Expensive side-effect-free computation may occur while durable state remains
retryable, but the final transaction must re-read and compare that state before
its first write. A stale attempt must raise a transition conflict and write no
artifact or evidence. Legacy durable `in_progress` records remain fail-closed and
must not become automatically retryable.


---

## RULE-120 — Controlled Pilot Startup Must Use the Safe Launcher

The controlled shadow pilot must start with `python -m src.pilot_launcher` and
no other server or UI command. The launcher must validate pilot mode, pilot
access configuration, an explicit private or loopback bind IP, and a valid port
before serving. The validated bind IP must be the exact host supplied to
Uvicorn; wildcard or public fallback is prohibited.

The ASGI target must remain `src.api:app`, reload must remain disabled, and
proxy and forwarded-header trust must remain disabled unless a later explicit
deployment-security decision replaces this rule. The pilot launcher must not
enable outbound email, and Streamlit is not pilot-approved.


---

## RULE-121 — Manual RFQ Send Recording Requires Authenticated Atomic Evidence

Only an authenticated pilot operator may record that an approved supplier RFQ
was sent manually outside MINAI. MINAI must perform no outbound action during
this transition. The authenticated identity, not a body claim, is the recorded
actor.

The transition requires an approved RFQ with its configured recipient, records
the send time, and moves it to `awaiting_response` so a supplier response may be
accepted. The RFQ update and one append-only manual-send evidence record must
commit atomically. Unknown, non-approved, repeated, and stale concurrent
attempts must fail without partial state or duplicate evidence.


---

## RULE-122 — Pilot Operators Must Use the Restricted Authenticated Workflow

The controlled operator workflow must use the authenticated pilot client against
localhost or an explicit private/loopback API address. Bearer tokens must be
supplied outside source control, never printed or persisted by the client, and
must not be forwarded through redirects or inherited proxies.

The client may expose only pilot-approved reads and human lifecycle decisions.
It must not expose supplier RFQ send, customer quote send, delivery adapters, or
direct SQLite mutation. State-changing calls must not be silently retried;
recovery requires reading current durable state and using returned identifiers.


## RULE-123 — External Pilot Operational Data Pack

Real controlled-pilot customer and supplier operational data must use one approved external pack under MINAI_PILOT_DATA_DIR.

Required layout:
- <pack-root>/data/customer_memory.json
- <pack-root>/data/supplier_capabilities.json
- <pack-root>/data/provenance_registry.json

The pilot launcher must fail closed without this pack. Readiness and runtime API must use the same resolved sources. HTTP clients cannot select filesystem paths.

Repository-directed symlinks, incomplete packs, provenance path mismatches, or final-byte SHA-256 mismatches must fail closed. External pack selection never replaces pilot_verified provenance, human verification, sanitized replay, or mandatory approvals.


## RULE-124 — Controlled Pilot Runtime Must Not Expose Regression Execution

The controlled pilot HTTP runtime must not expose an HTTP route that executes
the regression or test harness.

Regression execution must remain CLI-only through
`python -m src.simulation.pilot_regression_suite`.

Production API imports must not depend on regression evaluator modules solely
for HTTP test execution. This rule must not weaken the canonical regression
gate.


## RULE-125 — Controlled Pilot Runtime Must Not Expose Supplier Simulation

The controlled pilot HTTP runtime must not expose supplier-response simulation
routes or depend on the supplier simulator for operational API behavior.

Synthetic supplier responses may be used only by explicit engineering,
regression or rehearsal workflows and must never be treated as real pilot
supplier evidence.


## RULE-126 — Controlled Runtime Must Be Simulation-Free and Build-Gated

Importing the controlled production/pilot FastAPI application must not load
`src.simulation` modules, whether by direct or transitive dependency.

Development, simulation and regression runners must remain outside the
operational runtime import graph.

All repository Python source under `src/`, `ui/` and the root controlled
entry point must pass syntax compilation before a pilot change is accepted.

The canonical pilot regression suite and controlled rehearsal must run in the
repository CI gate for pull requests and pushes to `main`.


## RULE-127 — One Workflow Must Use One Coherent Operational Data Source

Supplier selection and downstream operational consistency validation must use
the same resolved supplier-capabilities source for the entire workflow stage.

A controlled-pilot operational data pack is not acceptable merely because its
files exist or their fingerprints match. Customer and supplier operational
master data must also pass their structural validators.

Structurally invalid operational master data must fail closed before controlled
pilot use and must block pilot readiness.


## RULE-128 — Road RFQ and Supplier Quote Must Fail Closed

For controlled-pilot road freight, MINAI must not create supplier RFQ drafts
without sufficient route, package, weight, ready-date and required-delivery
facts.

No eligible supplier means operator intervention; an empty supplier workflow is
not a valid operational state.

A supplier clarification response does not consume the RFQ. The same RFQ may
accept a later final supplier response.

A supplier price must not become a customer quote merely because cost and
currency are present. The quote must also have a valid transit duration,
unexpired validity date, explicit vehicle availability, matching equipment,
explicit all-in cost scope, known included/excluded charges with no exclusions,
and a delivery projection that meets the customer's required delivery date.

Commercially unsafe supplier responses must remain unselectable while
preserving their evidence and rejection reasons.

A supplier response entered directly by an operator must be recorded as
`manual`; the client must not choose another source label. The authenticated
operator identity must be retained as `recorded_by`.


## RULE-129 — Pilot Sender Trust and Privacy Must Fail Closed

Active pilot customers must have explicit trusted sender addresses or domains.
Trust rules that are malformed or ambiguous across customer identities must not
be accepted.

Supplier contact email addresses used as RFQ response identity evidence must
not belong to multiple supplier records. Clarification and final responses on
the same RFQ must continue to come from the RFQ's trusted supplier contact.

Pilot readiness requires 2–3 active trusted customer profiles and 3–5 active
suppliers with usable active primary RFQ contacts.

International phone numbers, IBANs, signatures and deterministic quoted-message
history must be minimized before customer mail reaches AI parsing.


## RULE-130 — Inbound Processing and Pilot Transport Must Fail Closed

Inbound mail exceeding the controlled body-size limit must not reach AI
processing.

A repeated external inbound message identity must be resolved to its existing
extraction proposal before another AI call. If the same identity appears with a
different sender or body fingerprint, processing must stop as an idempotency
conflict.

AI extraction must use bounded request duration and retry count. Provider
failures must be surfaced through sanitized controlled errors.

Pilot SQLite evidence files must remain private to the operating account on
POSIX hosts.

Bearer-authenticated pilot traffic may use plaintext HTTP only on loopback.
Private-network pilot bindings and operator connections must use HTTPS with TLS
material stored outside the repository.


## RULE-131 — Every Customer Quote Edit Requires a Fresh Exact Approval

Operations personnel may freely edit the complete customer quotation email.

Supplier quote source facts must not be overwritten by customer-facing edits. Every edit must be durably versioned with operator identity and before/after snapshots.

Editing a pending or approved quote must invalidate that approval and create a new pending approval for the exact revised subject, body and structured customer price. Stale revisions based on an older approval ID must fail closed.

Consistency warnings are advisory and must remain visible, but must not silently rewrite the operator's wording. Quote revision must never trigger autonomous outbound delivery.

## RULE-132 — Verified Pilot Operational Data Is Immutable

Before verification, guided pilot-data intake must validate proposed customer and supplier datasets before writing them to the external operational data pack.

Customer and supplier intake must remain outside the repository, respect controlled-pilot cardinality and identity/contact requirements, and avoid exposing trusted sender or supplier contact email values in listing output.

Final verification requires explicit human confirmation and exact-byte SHA-256 fingerprints. The presence of a provenance registry freezes the pack: guided mutation and repeated verification must fail closed rather than overwrite verified evidence.

Any change to verified customer or supplier operational data requires a new pack version and a complete fresh verification cycle. Removing or bypassing verification evidence to edit a frozen pack is not an approved pilot workflow.

## RULE-133 — Pilot Contact Addresses Must Not Be Command-Line Arguments

The supported guided pilot-data CLI must collect trusted customer sender addresses, trusted sender domains and supplier primary RFQ contact email addresses through interactive hidden input rather than command-line arguments.

These contact values may be written only to the approved external operational data pack as required identity evidence. Guided list output must continue to omit the address values themselves. Regression injection may bypass interactive prompting only for deterministic synthetic tests.

## RULE-134 — Authorized Sanitized Replay Must Be External, Explicit and Evidence-Bound

Historical replay input must be pre-sanitized before MINAI receives it, must remain outside the repository, and must not be treated as trusted customer identity evidence.

Authorized replay may use the production AI parser only after explicit confirmation of pre-sanitization, approved OpenAI data use, and disabled autonomous supplier/customer outbound. The selected customer and supplier operational datasets must pass production pilot provenance and structural validation.

Extraction proposals are scored as AI evidence only. Operational replay after the extraction checkpoint must use operator-confirmed historical truth; unknown required safety truth must stop at extraction confirmation.

When a replay evidence receipt is requested, the Git worktree must be clean. The receipt must bind the run to the exact Git commit, replay-input SHA-256, verified customer-memory SHA-256, verified supplier-capabilities SHA-256, privacy-transform version, safe aggregate metrics, and safety-critical mismatch count.

Replay input or operational data mutation during execution must block receipt creation. Receipt files must be create-only, stored outside the repository, and must not contain case IDs, sender addresses, customer identities, raw/sanitized message text, secrets, or operational contact values.

A replay receipt does not prove trusted-sender customer identity and does not by itself authorize pilot GO.

## RULE-135 — Human-Obvious Road Facts Must Not Cause Redundant Clarification

For trusted inbound customer mail, the customer identity established by the
verified sender gate must follow the extraction and operational workflow so
customer memory can be applied without requiring the customer name to be
repeated in the message body.

For Turkish road operations, deterministic source evidence may resolve facts
that an experienced operator would treat as unambiguous. Explicit import and
export direction may establish the Türkiye endpoint when that endpoint country
is omitted. Explicit road signals such as karayolu, tır/truck, FTL, LTL and
parsiyel may establish road mode when no conflicting transport mode is stated.
Explicit relative availability such as bugün, yarın, hazır or hemen may be
resolved against the inbound message date; negative availability must never be
converted into a positive date.

A commodity profile flag named `high_value_candidate` is a review signal only
and must not become confirmed `is_high_value=true` source truth.

Non-critical commodity clarification items must remain advisory and must not
become blocking merely because the road RFQ readiness layer runs after the
commodity missing-information layer.

For Türkiye-based international road supplier capability data, a supported
foreign lane country applies in both directions between Türkiye and that
country unless stricter exact-route evidence says otherwise. This symmetric
rule does not authorize unrelated foreign-to-foreign lanes.

## RULE-136 — Standard Turkish Road Quote Commercial Semantics

This rule supersedes only the stricter standard-road commercial metadata
requirements in RULE-128; RULE-128's evidence preservation, deadline safety,
and fail-closed handling of explicit contradictions remain in force.

For a standard Turkish road freight RFQ, supplier price plus currency and a
usable transit duration are sufficient commercial foundations when the
shipment itself is firm-quote ready. A separate supplier quote validity date
and a separate vehicle availability/reservation date are optional. If a
supplier provides a parseable validity date, an already-expired quote remains
unusable; if a validity date is provided and used, it must be carried to the
customer-facing quote.

Standard Turkish road freight pricing is treated as all-in by default. The
supplier does not need to repeat an `all_in` label or enumerate included and
excluded cost lists. An explicit base-freight-plus-extras statement or an
explicit excluded/additional charge is a commercial exception and must not be
silently converted into the normal all-in customer quote.

A supplier replying to the exact RFQ is treated as accepting the requested
equipment unless the supplier explicitly proposes a different equipment type.
An explicit equipment mismatch remains blocking.

Normal loading/unloading-site equipment such as forklift organization is the
customer/site responsibility unless the commercial request explicitly makes it
a carrier-provided charge.

## RULE-137 — Supplier Negative and Incomplete Responses Must Advance the Work

A terminal supplier response such as `no_capacity` or `declined` must not leave
an operator to recreate the next routine step. If another selected eligible
supplier exists, MINAI prepares the next supplier RFQ draft automatically and
stops at the existing human RFQ approval gate. No automatic outbound send is
authorized by this rule.

A quoted supplier response that contains a fixable commercial gap must preserve
the original response evidence, reopen that same RFQ as
`clarification_required`, and prepare a supplier follow-up draft asking only
for the missing or contradictory commercial facts. The same trusted supplier
contact may then provide a later final response on the same RFQ reference.

A supplier that cannot meet an explicit customer delivery deadline may be
skipped in favor of the next eligible supplier; the deadline itself must not be
weakened or removed to make a quote selectable.

## RULE-138 — Indicative Road Quotes Are Explicitly Non-Binding

When the customer explicitly asks for an `indikatif` / `indicative` price,
MINAI must mark the shipment `quote_mode=indicative`. Indicative pricing is a
budget exercise for a future or not-yet-firm shipment and is not a vehicle
reservation or binding freight commitment.

For an indicative standard road request, route-level country information is
enough to begin supplier pricing. Firm-quote requirements such as exact weight,
package dimensions, cargo-ready date and delivery deadline must not create
clarification solely because they are absent. Explicit special-risk signals
such as ADR, reefer, oversize/project cargo or another stated special equipment
condition remain authoritative and must not be erased by indicative mode.

One-ended indicative language may establish the Türkiye endpoint only when the
message itself gives a clear outbound/inbound direction (for example `gider`,
`gelir`, export/import). Ambiguous direction must remain unresolved rather than
inventing an endpoint.

Supplier indicative RFQs must say clearly that the request is indicative,
non-binding and not a vehicle reservation. For an indicative standard-road
supplier response, price and currency are enough; transit, validity and vehicle
availability are optional unless explicitly provided.

The customer-facing indicative quote must prominently state that it is
non-binding and that current freight and vehicle availability will be
reconfirmed when the shipment becomes real. A later firm shipment requires a
fresh firm-quote workflow; an old indicative price must not silently become a
booking or firm customer quote.

## RULE-139 — Pilot Markup Is a Test Assumption; Production Profitability Is Configurable

The controlled pilot may use a fixed 15% markup to keep deterministic pricing
regressions and live smoke tests stable. This is test configuration, not a
universal freight-pricing rule.

The production product must obtain profitability from agency configuration and
must permit an authorized quote-specific override before final customer quote
approval. A quote-specific override must be explicit and auditable; MINAI must
not silently replace the agency's configured commercial policy.

Customer-facing quote drafts must not display placeholder punctuation or
optional commercial fields as `Belirtilmedi` when no supplier fact exists. A
missing optional transit or validity field in an indicative quote is omitted;
provided facts remain visible and preserved.

## RULE-140 — Customer Quote Manual-Send Evidence Is Revision-Bound and Append-Only

An approved customer quote may be recorded as manually sent only while the
specified approval is still the current approval and the quote passes the same
final-output send-safety checks used for manual handoff.

The durable evidence must identify the quote case, approval ID, revision number,
recipient address, sending operator, send timestamp and
`source=manual_external_send`. The same approval/revision must not accept a
second manual-send record.

Revising a previously sent quote must preserve all earlier send evidence. A
freshly revised quote requires fresh approval and, if actually sent, a new
manual-send evidence record. Recording evidence never performs a provider send
and never weakens the existing human-approval boundary.

## RULE-141 — High-Value Status Must Not Be Invented or Used as a Universal Stop

If cargo value is unknown, MINAI keeps `is_high_value` unknown and continues a
standard road pricing workflow when the other required commercial and safety
facts are sufficient. It must not ask for cargo value solely to fill a field.

If high value is explicitly confirmed, MINAI flags the shipment for human review
of carrier liability, optional additional cargo insurance, security requirements
and carrier acceptance. High value alone does not exclude the shipment from the
pilot and does not automatically require management review unless an agency
policy explicitly configures such a threshold.

High-value status does not automatically change the requested vehicle to a box
trailer. Explicit customer equipment remains authoritative unless a real safety,
carrier-capability or commercial constraint requires an operator-reviewed change.
Explicit Turkish statements such as `Isı kontrollü değildir` establish
`is_temperature_controlled=false` and must not remain unknown.


## RULE-142 — External RFQ Notes Must Contain External Facts Only

Supplier-facing RFQs must not expose internal MINAI annotations such as
`[COMMODITY PROFILE]` notes. These annotations may remain available to internal
risk, consistency and operator-review logic, but they are not supplier facts.

When `special_notes` contains both a genuine customer/operator note and an
internal commodity-profile annotation, MINAI sends only the genuine external
note. When only internal annotations remain, the supplier RFQ omits the special
notes field.


## RULE-143 — Bare Rates and Historical Supplier Mail Must Fail Safely

If a supplier reply, after privacy minimization, contains only a positive amount
and supported ISO currency, MINAI records it as `quoted` with exactly that cost
and currency. All other commercial fields remain unknown unless supplied.

A supplier email without an explicit or subject RFQ reference may use sender
identity only when its received timestamp is present and is not earlier than the
RFQ's durable send timestamp. Historical mail must never be opportunistically
attached to a newly opened RFQ from the same supplier.

## RULE-144 — Ask Only the Missing Supplier Fact and Preserve Same-RFQ Provenance

When a firm road quote is commercially blocked only by a fixable missing supplier
fact, MINAI keeps the same RFQ and prepares a durable clarification follow-up that
asks only for the missing or contradictory fact. The follow-up must be human
approved before it can be marked as manually sent.

A follow-up reply such as `4 gün` may complete a prior `2400 EUR` quote on the same
RFQ. MINAI must retain the earlier price/currency as inherited supplier evidence,
record which fields were inherited and link the consolidated response to the prior
response timestamp. It must not ask the supplier to repeat already trustworthy
commercial facts merely to satisfy a storage schema.

Each follow-up has its own sequence and manual-send evidence. Repeated workflow
resumes must reuse an active draft/approved/awaiting-response follow-up instead of
creating duplicate outbound requests.
For sender-identity-only correlation while a clarification is awaiting response,
the active follow-up send timestamp is the minimum accepted inbound time; the
initial RFQ send timestamp alone is not sufficient.

## RULE-145 — Follow-Up Approval Access Does Not Weaken the Send Boundary

Authenticated pilot operators may read a durable supplier follow-up, approve it,
and record durable evidence after a manual external send. The pilot allowlist must
not expose an automated follow-up send endpoint. A successful approval is not
evidence that the message was sent.

## RULE-146 — One RFQ Produces One Current Quote Candidate

Supplier quote comparison must contain at most one current candidate per RFQ.
When multiple response snapshots exist, the latest received response supersedes
earlier snapshots for comparison and selection while all historical responses
remain durable evidence. Commercial-safety results must never be shared across
different response snapshots merely because they have the same RFQ ID.

## RULE-147 — Pricing Policy Resolution Is Mandatory Before Customer Price Creation

For P1-41 and later runtime behavior, the earlier fixed 15% customer-price default
is superseded. MINAI must resolve pricing in this order:

1. explicit quote override;
2. pricing policy on the verified customer profile;
3. configured agency default.

If none resolves, MINAI must stop at `pricing_policy_required`; it must not infer a
profitability percentage from customer sensitivity, prior test fixtures or any
other unrelated field.

`cost_markup_percentage` applies a percentage to supplier cost.
`gross_margin_percentage` targets gross margin on the final sales price.
`fixed_profit` adds a fixed amount in the quote currency. `manual_sell_price` is
an exact human/commercial sell price and receives no automatic rounding.

Agency rounding is explicit configuration and may vary by currency. Every created
customer quote must retain the effective policy source and formula so its approval
snapshot remains auditable. `price_sensitivity` is descriptive customer memory and
must never be treated as a numeric pricing rule.

## RULE-148 — Initial Supplier RFQ Batch Must Follow an Explicit Dispatch Policy

The supplier shortlist may contain up to the permitted supplier maximum without implying that all suppliers are contacted immediately. Initial RFQ draft creation must follow the workflow's snapshotted supplier dispatch policy.

- `sequential` requires `initial_supplier_count = 1`.
- `parallel` requires `initial_supplier_count` between 2 and 3.
- Missing agency dispatch configuration preserves the backward-compatible `sequential / 1` behavior.
- Invalid agency dispatch configuration must fail at controlled-pilot startup rather than silently selecting an unintended outreach strategy.
- Creating two or three parallel RFQ drafts does not bypass human approval and does not send any supplier email automatically.
- While any already-created RFQ remains active (`draft`, `approved`, `sent`, `awaiting_response`, or clarification), terminal failure from another supplier must not expand beyond the intended active batch.

Agency-configurable hybrid timeout/fallback behavior requires a separate explicit rule before runtime activation.

## RULE-149 — Outlook Provider Sending Must Preserve the Human Send Gate

Adding Microsoft delegated `Mail.Send` capability must not collapse approval and sending into one implicit action. Supplier RFQ approval remains a separate state transition from external delivery.

When an operator explicitly authorizes sending, MINAI may call Microsoft Graph for the exact approved, unsent message. The workflow may advance to a sent/awaiting-response state only after Graph returns HTTP 202. Any authentication failure, missing permission, provider exception, redirect, or non-202 response must fail safely without durable sent evidence.

## RULE-150 — Customer Quote Automated Send Evidence Must Be Provider-Confirmed and Idempotent

For an approved customer quote revision, automated delivery must use the exact current approval snapshot and recipient supplied for the send operation. Before calling the provider, MINAI must reject stale approval IDs and any revision that already has manual or automated sent evidence.

Durable automated sent evidence may be appended only when the outbound provider returns `status = sent` with a provider name, provider delivery reference and sent timestamp. Failed, rejected or unavailable-provider results must not create sent evidence.

The controlled pilot route for automated customer quote delivery remains an explicit send action. Quote creation and approval do not imply delivery. The same approval/revision must never be sent twice through the automated route, and a manual-sent record must not be added after automated delivery evidence already exists.

## RULE-151 — Approval Mutations Must Synchronize Durable Quote-Case State

When a current quote approval is approved, rejected or invalidated, every persisted QuoteCase referencing that approval ID must be updated with the current approval object. If the quote case contains the supplier quote, customer quote and quote draft, its `quote_send_safety` must be recomputed and persisted from the new approval state.

The controlled API must pass the quote-case repository into approval transitions so approval and case updates share one atomic SQLite transaction. A stale embedded approval may never be treated as an independent authorization source; final output and automated send continue to verify the authoritative current approval repository.

## RULE-152 — Supplier RFQ Automated Delivery Must Be Approved, Explicit and Auditable

Controlled supplier RFQ delivery is permitted only as an authenticated explicit operator action against an RFQ currently in `approved` state with a recipient address. Approval and delivery remain separate operations.

The RFQ may advance to `awaiting_response` only after the outbound provider reports `sent` with provider name, provider delivery reference and send timestamp. MINAI must persist those fields as durable automated-send evidence. Provider failure, missing provider metadata, an already-sent RFQ, or existing sent evidence must not cause another provider send or a false lifecycle advance. Manual and automated send evidence remain alternative delivery paths for one RFQ.
