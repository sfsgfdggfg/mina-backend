# P0.14 Pilot Operational Data Intake

## Amaç

Gerçek shadow pilot öncesinde doğrulanmış müşteri ve tedarikçi operational dataset'lerini hazırlamak.

Repository'deki mevcut `customer_memory.json` ve `supplier_capabilities.json` demo veridir. Gerçek pilot verisi bunların etiketini değiştirerek oluşturulmayacak.

## Veri nerede tutulacak?

Gerçek pilot master data **Git'e commit edilmeyecek**.

Onaylı harici bir pilot-data dizininde üç dosya birlikte tutulacak:

- `customer_memory.json`
- `supplier_capabilities.json`
- `provenance_registry.json`

Bu üç dosya tek bir coherent operational data pack oluşturur.

## İlk pilot için hedef

Başlangıçta:

- 2–3 gerçek, düzenli karayolu müşterisi
- 3–5 gerçek karayolu tedarikçisi

Yalnız pilot kapsamıyla gerçekten ilgili ve operasyon ekibinin doğrulayabildiği kayıtlar kullanılmalı.

## Customer memory

Desteklenen ana alanlar:

- `customer_name`
- `active`
- `aliases`
- `trusted_sender_addresses`
- `trusted_sender_domains`
- `default_commodity`
- `default_equipment_type`
- `price_sensitivity`
- `time_sensitivity`
- `default_pickup_city`
- `default_pickup_area`
- `default_pickup_country`
- `default_delivery_city`
- `default_delivery_country`
- `operational_notes`

Her müşteri için operasyon sahibi şunları doğrulamalı:

1. Resmi/kanonik müşteri adı
2. Gerçekte kullanılan alias'lar
3. Güvenilir gönderen e-posta adresleri
4. Gerekliyse güvenilir domain'ler
5. Varsayılan ürün gerçekten güvenilir mi?
6. Varsayılan ekipman gerçekten güvenilir mi?
7. Yükleme lokasyonu tekrar kullanılabilir bir default mu?
8. Teslim lokasyonu gerçekten default kabul edilebilir mi?
9. Fiyat/zaman hassasiyeti bilinen davranışa mı dayanıyor?
10. Operational notes gerçek, güncel ve güvenli mi?

Domain-wide trust ancak gerçekten güvenliyse kullanılmalı. Mümkün olduğunda tekil trusted sender address daha güvenlidir.

**Mail body müşteri kimliği kanıtı değildir.**

## Supplier capabilities

Her tedarikçi için doğrulanacak alanlar:

- `supplier_name`
- `active`
- `role`
- `route_regions`
- `countries`
- `service_types`
- `equipment_types`
- `special_capabilities`
- `priority_routes`
- `reliability_score`
- `price_score`
- `speed_score`
- `notes`
- `contacts`

Operasyon sahibi şunları doğrulamalı:

1. Tedarikçi kimliği
2. Aktif/pasif durumu
3. Primary / backup / specialist rolü
4. Gerçekte hizmet verilen ülkeler
5. FTL/LTL yetkinliği
6. Gerçekte mevcut ekipman
7. Gerçek operasyon geçmişine dayanan priority route'lar
8. Aktif RFQ/pricing kontağı
9. Reliability score'un operasyonel dayanağı
10. Price score'un operasyonel dayanağı
11. Speed score'un operasyonel dayanağı
12. Notes alanlarının varsayım değil gerçek bilgi olması

ADR, reefer veya başka uzmanlıklar tahmin edilerek eklenmeyecek.

## Pilot kapsamı

İlk controlled pilot:

- road only
- human operated
- tek pilot lojistik firması
- autonomous outbound yok

Pilot dışında:

- ADR
- reefer / temperature controlled
- medical / pharma
- chemical
- high-value
- oversize / project
- multimodal
- mixed currency

## Provenance doğrulaması

Operational dataset ancak FINAL byte'lar operasyon sahibi tarafından doğrulandıktan sonra pilot için kullanılabilir.

Her dataset için:

- `classification = pilot_verified`
- `operational = true`
- `pilot_usable = true`
- `verified_by` dolu olmalı
- `verified_at` timezone-aware olmalı
- SHA-256, kullanılan dosyanın exact hash'i olmalı

**Hash alındıktan sonra dosya değiştirilmez.**

Her byte değişikliği yeni hash ve yeni verification gerektirir.

## Doğru sıra

1. Customer draft hazırlanır.
2. Supplier draft hazırlanır.
3. Operasyon sahibi kayıtları tek tek inceler.
4. Belirsizlikler çözülür.
5. Final dosyalar freeze edilir.
6. Şema validasyonu yapılır.
7. SHA-256 alınır.
8. Provenance registry hazırlanır.
9. Hash'ler tekrar doğrulanır.
10. Verifier ve timestamp kaydedilir.
11. Readiness assessment çalıştırılır.
12. Authorized sanitized historical replay yapılır.
13. Tüm blocker'lar kapanmadan gerçek pilot başlamaz.

## Yasak kestirmeler

Şunları yapma:

- demo veriyi `pilot_verified` olarak etiketleme
- demo isimlerini gerçek firmalarla değiştirip kullanma
- supplier score uydurma
- trusted sender/domain tahmin etme
- mailbox arşivini operational dataset'e koyma
- parola/token/API key saklama
- gerçek operational master data'yı Git'e commit etme
- GO almak için provenance kontrolünü zayıflatma

## Teknik external pack layout

`MINAI_PILOT_DATA_DIR` üç JSON dosyasının bulunduğu `data/` klasörünü değil, external pack root'unu gösterir.

Örnek:

```text
/approved/external/minai-pilot/
└── data/
    ├── customer_memory.json
    ├── supplier_capabilities.json
    └── provenance_registry.json
```

Örnek environment:

```bash
export MINAI_PILOT_DATA_DIR=/approved/external/minai-pilot
```

Bu layout mevcut provenance registry'nin `data/customer_memory.json` ve
`data/supplier_capabilities.json` path semantiğini korur.

Controlled pilot launcher external pack root olmadan başlamaz. Pack root,
`data/` klasörü ve üç zorunlu dosya repository dışında olmalıdır. Resolver
symlink ile repository içine geri yönlendirilmiş `data/` veya dataset
dosyalarını kabul etmez.

Development'ta environment değişkeni verilmezse repository'deki demo/default
dataset'ler kullanılmaya devam eder. Bu fallback controlled pilot launcher için
geçerli değildir.

Readiness assessment ve operational API aynı resolved `OperationalDataSources`
paketini kullanır. HTTP request body üzerinden filesystem path veya alternatif
operational dataset seçilemez.

External pack seçimi tek başına pilot yetkisi değildir. `customer_memory` ve
`supplier_capabilities` yine production provenance doğrulayıcısından geçmeli;
registered path, consumed path ve final-byte SHA-256 uyuşmazlığı fail-closed
blok üretir.
