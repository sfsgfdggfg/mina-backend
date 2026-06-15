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

