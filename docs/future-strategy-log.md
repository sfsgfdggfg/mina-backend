# MINAI Future Strategy Log

> **Amaç:** Güncel geliştirme akışını bozmadan; geleceğe dönük stratejileri, rakiplerden öğrenilen dersleri, fırsatları, olası engelleri ve henüz uygulanmayacak fikirleri kalıcı olarak saklamak.
>
> **Bu dosya roadmap değildir.** Buraya giren hiçbir madde otomatik olarak geliştirme önceliği kazanmaz.

## 1. Çalışma Kuralı

Bu dosya **append-only stratejik park alanı** olarak kullanılacaktır.

Yeni bir fikir, rakip gözlemi, stratejik çıkarım veya ileride çözülmesi gereken sorun ortaya çıktığında önce buraya eklenir. Böylece o anki sprint/pilot/geliştirme işi bölünmez ve fikir kaybolmaz.

Bir madde ancak açık bir ürün kararıyla aktif geliştirmeye alınır. Aktif geliştirmeye alınan stratejik karar gerektiğinde `docs/decision-log.md` dosyasına ayrıca kaydedilir ve ilgili teknik/ürün backlog'una taşınır.

### Varsayılan durumlar

- **PARKED** — Değerli olabilir; şu an uygulanmayacak.
- **WATCH** — İzlenecek rakip, teknoloji, pazar veya risk.
- **RESEARCH** — Karar vermeden önce ek veri gerekir.
- **CANDIDATE** — Roadmap'e alınmaya aday.
- **PROMOTED** — Açık kararla aktif roadmap/backlog'a taşındı.
- **REJECTED** — Bilinçli olarak uygulanmamasına karar verildi; gerekçesi korunur.

**Kural:** Yeni kayıtların varsayılan durumu `PARKED` veya `WATCH` olmalıdır. Böylece gelecek fikirleri bugünkü iş akışını sessizce değiştirmez.

---

# 2. MINAI Uzun Vadeli Stratejik İlkeleri

## STRAT-001 — MINAI bir e-posta parser'ı değil, Freight Operations OS olmalıdır
**Durum:** PARKED / yön gösterici ilke
**Kaynak:** MINAI ürün vizyonu + Vooma rakip incelemesi, 2026-09-14

Email → Quote ilk ürün ve öğrenme alanıdır; nihai ürün tanımı değildir.

Uzun vadede MINAI'nin görevi:

1. işi anlamak,
2. gerekli bilgiyi toplamak,
3. karar önermek veya yetkisi varsa karar vermek,
4. dış sistemlerde/iletişim kanallarında aksiyon almak,
5. sonucu takip etmek,
6. istisnayı insana taşımak,
7. gerçekleşen sonuçtan öğrenmek

olmalıdır.

**Stratejik sonuç:** İlk ürünün başarısı yalnızca “maili doğru parse ediyor mu?” ile ölçülmemeli; gelecekte karar ve icra yapabilecek veri modeli, audit trail, provenance ve workflow state temeli korunmalıdır.

---

## STRAT-002 — Bugünkü dar kapsam korunmalı; gelecek fikirleri pilotu dağıtmamalıdır
**Durum:** ACTIVE PRINCIPLE

Vooma'nın bugün geniş bir quote-to-cash ürününe ulaşmış olması, MINAI'nin bugün aynı kapsamı bir anda geliştirmesi gerektiği anlamına gelmez.

MINAI'nin avantajı; dar bir akışta operasyonel doğruluğu, güveni ve gerçek kullanıcı değerini kanıtlayarak genişlemektir.

**Kural:** Yeni görülen rakip özelliği doğrudan backlog'a eklenmez. Önce bu dosyaya kaydedilir. Ancak mevcut ürün aşamasında tekrarlanan gerçek müşteri ihtiyacı veya açık stratejik karar varsa roadmap'e alınır.

---

## STRAT-003 — Kademeli otonomi MINAI'nin temel ürün mimarisi olmalıdır
**Durum:** PARKED / mimari yön
**Vooma'dan ders:** Rakip; operatör tıklaması, draft ve tam otomatik çalışma seviyelerini birlikte destekliyor.

MINAI uzun vadede aynı workflow için farklı otonomi seviyelerini desteklemelidir:

- yalnızca analiz/öneri,
- MINAI hazırlar → insan onaylar,
- düşük riskli aksiyonları otomatik yapar → istisnaları insana taşır,
- belirli müşteri/workflow için tam otomatik çalışır.

Otonomi seviyesi global olmak zorunda değildir; acenta, müşteri, workflow, aksiyon türü ve risk seviyesine göre değişebilmelidir.

**Kritik prensip:** İnsan escalation bir “başarısızlık” değil, tasarlanmış çalışma modu olmalıdır.

---

## STRAT-004 — Operasyon hafızası MINAI'nin asıl uzun vadeli moat'ı olmalıdır
**Durum:** PARKED / yön gösterici ilke

Model sağlayıcısı veya kullanılan LLM tek başına kalıcı rekabet avantajı değildir.

MINAI'nin zaman içinde biriktirmesi gereken benzersiz kurumsal hafıza:

- müşteri tercihleri ve istisnaları,
- müşteri bazlı eksik bilgi toleransı,
- rota davranışları,
- tedarikçi güçlü/zayıf hatları,
- fiyat ve teklif geçmişi,
- cevap hızı ve hizmet kalitesi,
- kazanılan/kaybedilen teklifler,
- operatörün MINAI önerisini neden kabul/reddettiği,
- SLA ve escalation örüntüleri,
- portal/agent/carrier çalışma biçimleri,
- şirket SOP'leri ve yazılı olmayan operasyon bilgisi.

**Hedef:** MINAI her müşteride zamanla o şirketin operasyonunu genel amaçlı bir AI'dan belirgin biçimde daha iyi anlayan bir sisteme dönüşmelidir.

---

## STRAT-005 — İnsan kararlarının sonucu da veri olmalıdır
**Durum:** PARKED

Sadece gelen ve giden e-postaları kaydetmek yeterli değildir.

Gelecekte mümkün olduğu ölçüde şu bağlantı saklanmalıdır:

`durum → MINAI önerisi → insan kararı → yapılan aksiyon → gerçek sonuç`

Bu yapı ileride:

- daha iyi öneri,
- confidence calibration,
- otomasyona güvenli geçiş,
- çalışan performans analizi,
- SOP keşfi,
- açıklanabilirlik

için temel veri olacaktır.

---

## STRAT-006 — MINAI'nin farkı international freight forwarder derinliği olmalıdır
**Durum:** ACTIVE PRINCIPLE
**Vooma gözlemi:** Vooma bugün ağırlıklı olarak Kuzey Amerika freight broker/carrier ve domestic trucking ekosistemine odaklıdır.

MINAI'nin stratejik ayrışma alanı:

- uluslararası freight forwarding,
- Türkiye ↔ Avrupa road freight,
- yabancı acenta/supplier ağı,
- road + sea + air ortak operasyon modeli,
- carrier/liner/airline portalları,
- local charges ve surcharge mantığı,
- teslim alma/dağıtım fiyatları,
- multimodal iş akışları,
- ülke/hat bazlı operasyon bilgisi,
- ileride gümrük ve bağlantılı operasyonlar.

**Kural:** Vooma'nın ABD trucking özelliklerini birebir kopyalamak yerine altında yatan operasyon prensibi çıkarılmalı ve freight-forwarder gerçekliğine uyarlanmalıdır.

---

## STRAT-007 — MINAI standalone chatbot değil, mevcut operasyon stack'inin execution/intelligence katmanı olmalıdır
**Durum:** PARKED
**Vooma'dan ders:** Güçlü değer, AI sohbet ekranından değil; TMS, pricing kaynakları, e-posta ve operasyon araçlarıyla entegrasyondan geliyor.

Uzun vadede MINAI:

- e-posta,
- TMS/ERP,
- supplier/carrier portalları,
- fiyat dosyaları,
- CRM,
- mesajlaşma/telefon kanalları

üzerinde çalışan ortak karar ve icra katmanı olmalıdır.

Müşterinin mevcut sistemlerini hemen değiştirmesini zorunlu kılmamak satış ve deployment açısından avantaj sağlayabilir.

---

## STRAT-008 — “Command Tower” yaklaşımı değerlendirilmelidir
**Durum:** PARKED
**Vooma'dan ders:** İnsan çalışanlar ve AI worker'lar aynı operasyonel kontrol katmanında yönetiliyor.

MINAI'de gelecekte tek bir kontrol yüzeyi şu unsurları gösterebilir:

- bugün bekleyen işler,
- AI'nın kendi yürüttüğü işler,
- insan onayı bekleyen aksiyonlar,
- escalation'lar,
- SLA riski,
- supplier response bekleyen işler,
- hata/istisnalar,
- operatör bazlı iş yükü ve performans,
- AI otomasyon oranı ve müdahale oranı.

Bu yapı mevcut ana sayfa/takvim yaklaşımının uzun vadeli evrimi olarak düşünülmelidir; bugün ayrı kapsam açılmaz.

---

## STRAT-009 — Premium değer üretirsek “ucuz AI aracı” olarak fiyatlanmamalıyız
**Durum:** WATCH / ticari strateji
**Vooma gözlemi:** Kamuya açık düşük fiyatlı self-service paket görünmüyor; satış modeli enterprise/premium deployment yönünde.

MINAI fiyatı yalnızca:

- kullanıcı sayısı,
- LLM token maliyeti,
- gönderilen mail sayısı

üzerinden düşünülmemelidir.

Asıl değer metriği ileride şu ekonomik sonuçlara bağlanmalıdır:

- operatör saat tasarrufu,
- daha hızlı quote response,
- daha yüksek win-rate,
- daha iyi satın alma fiyatı,
- daha az kaçırılan iş/SLA,
- daha az manuel hata,
- aynı ekip ile daha yüksek shipment hacmi.

**Not:** Bugün nihai fiyat belirlenmiyor. Bu kayıt yalnızca MINAI'nin “ucuz AI email assistant” kategorisine kendisini gereksiz yere kilitlememesi için stratejik hatırlatmadır.

---

## STRAT-010 — “Shadow TMS / Operations Intelligence Layer” uzun vadede değerlendirilmelidir
**Durum:** PARKED

MINAI başlangıçta TMS yerine geçmek zorunda değildir. Ancak zamanla e-posta, quote, supplier, customer, karar ve sonuç verisini tek bir anlamlı modelde biriktirirse müşterinin mevcut TMS'inden farklı ve daha zengin bir operasyon intelligence katmanına dönüşebilir.

Bu katman ileride:

- route intelligence,
- supplier ranking,
- customer behavior,
- pricing intelligence,
- anomaly detection,
- workload forecasting,
- autonomous execution

için temel olabilir.

TMS replacement kararı ayrı ve çok daha sonraki bir stratejik karardır; bu kayıt TMS yapma kararı değildir.

---

# 3. Vooma Rakip İncelemesinden Kaydedilen Fırsatlar

## COMP-VOOMA-001 — Quote → Build → Schedule → Cover → Track → Collect genişleme modeli
**Tarih:** 2026-09-14
**Durum:** WATCH

### Gözlem
Vooma dar bir email/load-entry probleminden başlayıp zamanla quote-to-cash boyunca yeni AI worker/workflow'lar eklemiş.

### MINAI için çıkarım
MINAI'nin ilk genişleme sırası bugün belirlenmemeli. Ancak Email → Quote sonrasında müşterilerde oluşan en büyük operasyonel darboğaz ölçülmeli ve bir sonraki modül gerçek kullanım verisine göre seçilmelidir.

Muhtemel gelecekteki alanlar:

- accepted quote → job creation,
- supplier booking/confirmation,
- shipment scheduling,
- tracking & exception management,
- POD/document collection,
- invoicing/collection support.

**Karar:** Şimdilik hiçbiri Phase 1 kapsamına eklenmiyor.

---

## COMP-VOOMA-002 — Customer-specific SOP ve memory görünür ürün nesnesi olmalı
**Tarih:** 2026-09-14
**Durum:** PARKED

MINAI zaten müşteri geçmişinden ve operasyon kurallarından yararlanmayı hedefliyor.

Gelecekte bu bilgi yalnızca model prompt'u veya gizli backend verisi olmamalı; gerektiğinde kullanıcı tarafından görülebilen/düzenlenebilen yapılandırılmış bir “müşteri çalışma hafızası / SOP” haline gelmesi değerlendirilmeli.

Örnek:

- bu müşteri genelde tenteli ister,
- teslim tarihini ilk mailde vermediyse süreç durmaz,
- şu ülke hattında şu supplier önceliklidir,
- şu müşteri için otomatik quote yasaktır,
- bu müşteri için maksimum X risk sınıfında otomatik aksiyon kullanılabilir.

---

## COMP-VOOMA-003 — Quote outcome / win-loss intelligence
**Tarih:** 2026-09-14
**Durum:** CANDIDATE-LATER

Her teklif mümkünse sonradan bir outcome ile bağlanmalıdır:

- won,
- lost,
- no response,
- cancelled,
- unknown.

Mümkünse kayıp nedeni de saklanmalıdır:

- fiyat,
- transit time,
- equipment availability,
- relationship,
- deadline miss,
- customer cancelled,
- unknown.

Bu veri yeterince biriktiğinde MINAI yalnızca “doğru fiyat maili yazan” değil, hangi teklif stratejisinin iş kazandırdığını öğrenen sisteme dönüşebilir.

---

## COMP-VOOMA-004 — AI + human ortak performans ölçümü
**Tarih:** 2026-09-14
**Durum:** PARKED

Gelecekte yalnızca çalışan performansı değil, AI ile çalışan ekip performansı da ölçülebilir:

- quote turnaround time,
- approval latency,
- AI suggestion acceptance/revision rate,
- human intervention rate,
- escalation reason,
- automation success rate,
- rework/error rate.

Amaç çalışanları cezalandırmak değil; hangi workflow'un otomasyona hazır olduğunu ve nerede sistemin yetersiz kaldığını ölçmektir.

---

## COMP-VOOMA-005 — Voice/telefon otomasyonu çekici ama erken aşamada risklidir
**Tarih:** 2026-09-14
**Durum:** WATCH

Vooma ve ABD freight pazarındaki AI voice örnekleri telefon otomasyonunun ölçek avantajını gösteriyor. Aynı zamanda robot görüşmelerinin carrier/dispatcher tarafında tepki yaratabileceğine dair pazar sinyalleri bulunuyor.

MINAI için prensip:

- Voice gelecekte değerlendirilebilir.
- İnsan ilişkisini bozabilecek kanallarda tam otomasyon varsayılan olmamalıdır.
- Kimlik, kayıt, consent, yanlış anlaşılma ve escalation tasarımı ayrıca ele alınmalıdır.

Bugün kapsam dışıdır.

---

# 4. Gelecekte Çözülmesi Muhtemel Engeller / Risk Register

## FUTURE-RISK-001 — Entegrasyon parçalanması
**Durum:** WATCH

Her müşteri farklı TMS, ERP, e-posta sistemi, portal ve Excel yapısı kullanabilir.

Olası ihtiyaçlar:

- connector abstraction,
- müşteri-spesifik adapter'ların core'dan ayrılması,
- graceful fallback to email/manual entry,
- integration health monitoring.

---

## FUTURE-RISK-002 — Müşteri bazlı kuralların “configuration hell”e dönüşmesi
**Durum:** WATCH

Çok sayıda müşteri ve istisna birikince birbirini çelişen kurallar oluşabilir.

İleride gerekebilecekler:

- rule precedence,
- scope hierarchy,
- effective rule preview,
- conflict detection,
- version history,
- “bu karar neden verildi?” açıklaması.

---

## FUTURE-RISK-003 — Öğrenme verisinin kirli veya yanlış olması
**Durum:** WATCH

Geçmiş insan kararları her zaman doğru değildir. MINAI eski alışkanlığı otomatik olarak “doğru SOP” kabul etmemelidir.

Gelecekte memory/learning katmanında:

- provenance,
- confidence,
- confirmation,
- recency,
- exception handling,
- explicit override

gerekebilir.

---

## FUTURE-RISK-004 — Otonomi arttıkça hata maliyeti doğrusal artmaz
**Durum:** WATCH

Draft'taki bir hata insan tarafından yakalanabilir; otomatik gönderilen yanlış quote veya yanlış supplier booking doğrudan mali zarara dönüşebilir.

Bu nedenle her workflow'un otomasyon seviyesi:

- geri döndürülebilirlik,
- parasal risk,
- müşteri ilişkisi riski,
- operasyon güvenliği,
- confidence,
- geçmiş başarı oranı

ile birlikte değerlendirilmelidir.

---

## FUTURE-RISK-005 — AI'nın insan ilişkisini zayıflatması
**Durum:** WATCH

Freight forwarding ilişki temelli bir sektördür. Tedarikçi ve müşteriyi sürekli robotla karşı karşıya bırakmak bazı segmentlerde ticari dezavantaj yaratabilir.

MINAI'nin hedefi mümkün olduğunca “insanı ortadan kaldırmak” değil; düşük değerli tekrarları otomatikleştirip insanı ilişki, müzakere ve istisna yönetimine taşımak olmalıdır.

---

## FUTURE-RISK-006 — ROI'nin ölçülememesi premium fiyatlandırmayı zorlaştırır
**Durum:** PARKED

MINAI yarattığı değeri kanıtlayamazsa müşteri ürünü yalnızca yazılım lisansı olarak kıyaslar.

İleride ürün telemetrisi şu değerleri mümkün olduğunca ölçebilmelidir:

- saved operator time,
- faster response,
- automated actions,
- prevented SLA misses,
- quote volume per employee,
- accepted vs revised AI actions,
- won/lost quote outcomes.

---

## FUTURE-RISK-007 — Model sağlayıcısına aşırı bağımlılık
**Durum:** WATCH

Model kabiliyeti, fiyatı veya API davranışı değişebilir.

Uzun vadede şirketin asıl IP'si:

- domain data model,
- workflow engine,
- operational memory,
- rules,
- evaluation suite,
- integrations,
- customer/supplier intelligence

olmalıdır; tek bir LLM sağlayıcısının özel davranışına kilitlenmemelidir.

---

## FUTURE-RISK-008 — Multi-tenant privacy ve veri izolasyonu büyüdükçe kritikleşir
**Durum:** WATCH

MINAI farklı acentalarda yaygınlaştığında müşteri, supplier, fiyat ve operasyon hafızasının tenant sınırlarının yanlış aşılması çok yüksek risk taşır.

Bugünkü privacy boundary yaklaşımı uzun vadeli ürün mimarisinde korunmalı; öğrenme/memory özellikleri bu sınırı asla bulanıklaştırmamalıdır.

---

# 5. Roadmap'e Taşıma Kriteri

Bu dosyadaki bir fikir ancak aşağıdaki türde kanıtlar oluştuğunda aktif roadmap'e aday yapılmalıdır:

- pilotta aynı problem tekrar tekrar görülüyor,
- birden fazla gerçek müşteri aynı ihtiyacı ifade ediyor,
- mevcut workflow'daki en büyük darboğaz ölçülmüş durumda,
- mevcut fazın başarı kriterleri büyük ölçüde tamamlandı,
- yeni özellik net ticari veya operasyonel değer yaratıyor,
- güvenlik/operasyon riski yönetilebilir,
- geliştirme maliyeti mevcut öncelikleri bozmayacak şekilde gerekçelendirilebiliyor.

Roadmap'e taşıma kararı verildiğinde:

1. bu kaydın durumu `PROMOTED` olarak ek bir notla güncellenir (eski içerik silinmez),
2. karar `decision-log.md` içine yazılır,
3. teknik/ürün backlog maddesi ayrıca oluşturulur.

---

# 6. Kayıt Şablonu

Yeni fikirler aşağıdaki kısa şablonla eklenebilir:

```md
## <TYPE-ID> — <Başlık>
**Tarih:** YYYY-MM-DD
**Durum:** PARKED | WATCH | RESEARCH | CANDIDATE | PROMOTED | REJECTED
**Kaynak:** müşteri / pilot / rakip / ekip / operasyon gözlemi / araştırma

### Gözlem
...

### MINAI için olası anlamı
...

### Neden şimdi yapılmıyor?
...

### Roadmap'e alma tetikleyicisi
...
```

---

# 7. İlk Rakip Kaydı — Vooma

## WATCH-COMPETITOR-001 — Vooma
**Tarih:** 2026-09-14
**Durum:** WATCH

### Neden izleniyor?

Vooma, MINAI'nin uzun vadeli vizyonuna en yakın bilinen rakip örneklerinden biridir. Email/load-entry kökeninden quote-to-cash AI workforce platformuna genişlemiştir.

### Öğrenilecek ana noktalar

- dar bir workflow ile başlayıp operasyon zincirine kademeli genişleme,
- müşteriye özel SOP/memory,
- progressive autonomy,
- execution-oriented integrations,
- human + AI command layer,
- quote outcome analytics,
- enterprise/premium değer konumlandırması.

### Körü körüne kopyalanmaması gerekenler

- ABD domestic trucking'e özgü workflow'lar,
- loadboard/carrier ekosistemine özel varsayımlar,
- relationship-sensitive süreçlerde agresif voice automation,
- sırf rakipte var diye scope genişletme.

### MINAI'nin savunulabilir farkı

International freight forwarding domain derinliği + supplier/customer/route operational memory + multimodal süreçler + güvenli kademeli otonomi.

---

## Son not

Bu dosyanın amacı fikir üretmek değil, **iyi fikirlerin yanlış zamanda geliştirilmesini engellerken unutulmasını da önlemektir.**

Güncel iş akışı kendi planında ilerler; gelecek burada birikir. Doğru zaman geldiğinde buradaki kayıtlar kanıtla birlikte roadmap'e taşınır.
