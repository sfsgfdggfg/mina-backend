# Sanitized Historical Replay Data Preparation

## Amaç

Gerçek controlled shadow pilot başlamadan önce, geçmiş gerçek taleplerden hazırlanmış anonimleştirilmiş örneklerle MINAI davranışını test etmek.

Bu replay şunlardan ayrıdır:

- canonical regression suite
- synthetic controlled-pilot rehearsal
- customer/supplier operational master data

Synthetic testlerin geçmesi historical replay yerine geçmez.

## Vaka seçimi

Pilot firmanın geçmiş gerçek karayolu operasyonlarından örnekler seçilir.

Başlangıç için önerilen hedef: 20–40 vaka.

Kolay vakalarla sınırlı kalma. Mümkün olduğunda şunları dahil et:

- standart FTL
- eksik bilgi içeren talepler
- eksik ağırlık veya ölçü
- belirsiz commodity
- paket/ağırlık ifadesi belirsiz talepler
- recurring customer örnekleri
- customer memory'nin yardımcı olması gereken vakalar
- customer memory'nin kullanılmaması gereken vakalar
- clarification gerektiren vakalar
- ADR, reefer, non-road, high-value ve oversize/project örnekleri

Out-of-scope vakalar özellikle değerlidir; MINAI'nin doğru şekilde durması gerekir.

## Sanitization MINAI'den önce yapılır

Replay harness'e raw historical mailbox verilmez.

Önceden kaldır veya değiştir:

- gerçek kişisel isimler
- gerçek e-posta adresleri
- telefon numaraları
- IBAN
- e-posta imzaları
- kişisel tanımlayıcılar
- gereksiz internal comment'ler
- credentials
- test için gerekmeyen müşteri/tedarikçi gizli referansları

Pseudonymous case_id kullan. Sender için .invalid domain kullan.

Replay harness'in güvenlik kontrolleri bir anonymization servisi değildir. Raw veriyi sessizce temizlemesini bekleme.

## Ground truth

Her vaka için deneyimli operasyoncu, o anda gerçekten bilinebilen bilgiyi işaretlemeli.

Üç durumu ayır:

- known
- unknown
- not applicable

Hindsight kullanma. Orijinal talepte olmayan ama operasyon tamamlandıktan sonra öğrenilen bilgiyi ground truth'a ekleme.

Ground truth, MINAI'nin o workflow anında makul biçimde erişebildiği bilgiyi temsil etmeli.

## Operatörün doğrulayacağı başlıklar

- customer identity expectation
- pickup country/city/postcode
- delivery country/city/postcode
- commodity
- gross weight
- package bilgisi
- dimensions
- service type
- equipment
- transport mode
- cargo ready date
- ADR state
- temperature-control state
- high-value state
- oversize/project state
- expected workflow disposition
- supplier progression allowed / blocked

## Safety vakaları

En az ADR, reefer / temperature-controlled, non-road, high-value, oversize / project ve kritik bilgi eksikliği örnekleri bulunmalı.

Bir safety exclusion'ın kaybolması normal extraction hatası değildir. Bu safety-critical mismatch'tir ve pilot GO öncesi araştırılmalıdır.

## Saklama

Sanitized replay JSONL repository dışında tutulur.

Git'e commit etme:

- raw historical emails
- sanitized replay JSONL
- case-data içeren replay report
- approval records

Çalıştırma:

python -m src.simulation.sanitized_replay --input /approved/external/path/replay.jsonl

P1.5 CLI external replay contract'ını validate eder; live AI extraction provider'ı kendi başına açmaz.

Actual AI replay için ayrıca onaylanmış adapter/data-use adımı gerekir.

## Replay değerlendirmesi

Keyfi bir yüzde belirleme. Örneğin 95% geçti = pilot hazır gibi bir kural kullanma.

Ayrı ayrı değerlendir:

- extraction mismatches
- missing facts
- unexpected inference
- clarification decisions
- scope decisions
- equipment decisions
- supplier progression
- safety-critical mismatches

Her safety-critical mismatch pilot GO öncesi çözülmeli veya açık biçimde anlaşılmalıdır.

## External operator review log

Önerilen alanlar:

- pseudonymous case_id
- outcome
- corrected fields
- clarification correct/incorrect
- scope decision correct/incorrect
- safety-critical mismatch yes/no
- operator comment
- follow-up action

Raw email text'i review log'a koyma; yalnız ayrıca onaylanmış secure storage policy varsa saklanabilir.

## Completion evidence

Authorized replay tamamlandığında readiness evidence yalnız compact metadata tutmalı:

- completed: true
- result: pass
- completed_at
- case_count
- safety_critical_mismatches: 0
- pilot commit SHA

Readiness evidence human attestation'dır. Bağımsız legal/privacy verification değildir.
