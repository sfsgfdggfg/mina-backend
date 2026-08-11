
# MINAI Freight OS

# Database Schema v1

## 1. Amaç

Bu doküman MINAI Freight OS içinde kullanılan temel veri modellerini tanımlar.

Mevcut MVP’de tüm veriler gerçek bir relational database içinde tutulmamaktadır.

Şu anki yapı:

```text
Customer Memory
→ data/customer_memory.json

Workflow Result
→ runtime response object

Test Cases
→ src/simulation/ai_email_test_cases.py

Backup Files
→ data/backups/
```

Ancak sistem büyüdükçe bu modeller ileride database tablolarına taşınacaktır.

Bu dokümanın amacı:

* hangi verilerin tutulacağını netleştirmek
* entity ilişkilerini tanımlamak
* ileride PostgreSQL / SQLite / başka database’e geçişi kolaylaştırmak
* AI workflow kararlarının izlenebilir olmasını sağlamaktır

---

## 2. Temel Veri Alanları

MINAI Freight OS’in ana veri grupları:

```text
Shipment
Customer Memory
Customer Memory Audit
Equipment Decision
Missing Information
Risk Assessment
Supplier Quote
Customer Quote
Generated Draft
Action Recommendation
Test Case
Import / Export / Backup Metadata
```

---

## 3. Shipment Schema

Shipment, müşteri mailinden çıkarılan operasyon talebidir.

Logical entity:

```text
Shipment
```

Önerilen alanlar:

| Field                   |          Type |    Required | Description                   |
| ----------------------- | ------------: | ----------: | ----------------------------- |
| id                      | string / uuid |      future | Shipment unique id            |
| customer_name           |        string |          no | Müşteri adı                   |
| pol                     |        string |         yes | Pickup / loading location     |
| pod                     |        string |         yes | Delivery location             |
| pickup_address          |        string |          no | Detaylı pickup adresi         |
| delivery_address        |        string |          no | Detaylı delivery adresi       |
| commodity               |        string | conditional | Mal cinsi                     |
| weight_kg               |        number | conditional | Brüt ağırlık                  |
| volume_cbm              |        number |          no | Hacim                         |
| pieces                  |        number |          no | Parça / palet adedi           |
| dimensions              |   list / json | conditional | Ölçüler                       |
| shipment_type           |        string |         yes | FTL / LTL                     |
| transport_mode          |        string |         yes | road / air / sea / multimodal |
| equipment_type          |        string |          no | Müşteri talep etmişse         |
| ready_date              | string / date |          no | Hazır tarih                   |
| expected_delivery_date  | string / date |          no | Beklenen teslim tarihi        |
| incoterm                |        string |          no | Belirtilmişse                 |
| adr_class               |        string |          no | ADR sınıfı                    |
| temperature_requirement |        string |          no | +4, -18 vb.                   |
| commodity_attributes    |          json |          no | Canonical commodity clarification answers |
| regulatory_exception_reviews |      json |          no | Pending/approved/rejected pre-quote document exception reviews |
| notes                   |        string |          no | Ek açıklamalar                |
| source_email_text       |          text |      future | Ham müşteri maili             |
| created_at              |      datetime |      future | Kayıt tarihi                  |

---

## 4. Shipment Type Rules

Shipment type değerleri:

```text
FTL
LTL
Unknown
```

Road Freight için varsayılan:

```text
FTL
```

LTL yalnızca müşteri açıkça parsiyel / partial / yarım parsiyel gibi ifade kullanırsa atanır.

---

## 5. Customer Memory Profile Schema

Customer Memory müşteri kartı değildir.

Amacı CRM gibi tam müşteri yönetimi değil, operasyonel varsayımlar üretmektir.

Current storage:

```text
data/customer_memory.json
```

Logical entity:

```text
CustomerMemoryProfile
```

Alanlar:

| Field             |         Type | Required | Description                       |
| ----------------- | -----------: | -------: | --------------------------------- |
| customer_name     |       string |      yes | Ana müşteri adı                   |
| active            |      boolean |      yes | Matching/enrichment için aktif mi |
| aliases           | list[string] |       no | Alternatif müşteri isimleri       |
| default_commodity |       string |       no | Varsayılan ürün                   |
| default_equipment |       string |       no | Varsayılan ekipman                |
| price_sensitivity |       string |      yes | low / medium / high               |
| time_sensitivity  |       string |      yes | low / medium / high               |
| default_pickup    |       string |       no | Varsayılan yükleme adresi         |
| default_delivery  |       string |       no | Varsayılan teslim adresi          |
| operational_notes | list[string] |       no | Operasyonel notlar                |
| created_at        |     datetime |      yes | İlk oluşturma zamanı              |
| last_updated_at   |     datetime |      yes | Son güncelleme zamanı             |
| last_updated_by   |       string |      yes | Değişikliği yapan kaynak          |
| change_note       |       string |       no | Değişiklik açıklaması             |

---

## 6. Customer Memory Active / Passive Rule

Customer Memory profilleri fiziksel olarak silinmez.

Bunun yerine:

```text
active = true
→ recognition ve enrichment için kullanılabilir

active = false
→ UI’da görünür ama matching/enrichment için kullanılmaz
```

Amaç:

* yanlışlıkla veri kaybını önlemek
* geçmiş operasyonel bağlamı korumak
* ileride audit trail için zemin hazırlamak

---

## 7. Customer Memory Reserved Terms

Aşağıdaki generic değerler müşteri adı veya alias olarak kullanılmaz:

```text
test
demo
deneme
sample
example
dummy
unknown
unknown customer
customer
company
client
müşteri
firma
```

Gerekçe:

AI parser belirsiz müşteri adlarında bu tip değerler üretebilir. Bu değerler Customer Memory ile eşleşirse sistem yanlış müşteriyi tanınan müşteri kabul edebilir.

---

## 8. Customer Memory Match Result Schema

Workflow sırasında Customer Memory lookup sonucu ayrı bir obje olarak tutulur.

Logical entity:

```text
CustomerMemoryResult
```

Alanlar:

| Field         |                         Type | Description                                |
| ------------- | ---------------------------: | ------------------------------------------ |
| matched       |                      boolean | Eşleşme bulundu mu                         |
| profile       | CustomerMemoryProfile / null | Eşleşen profil                             |
| source        |                       string | shipment.customer_name / email_text / none |
| matched_by    |                       string | customer_name / alias / none               |
| notes_applied |                 list[string] | Workflow’a uygulanan notlar                |

---

## 9. Missing Information Schema

Eksik bilgi kontrolü workflow gate olarak çalışır.

Logical entity:

```text
MissingInformationResult
```

Alanlar:

| Field                  |         Type | Description                               |
| ---------------------- | -----------: | ----------------------------------------- |
| can_continue           |      boolean | Workflow quote üretmeye devam edebilir mi |
| missing_fields         | list[string] | Eksik alanlar                             |
| reasons                | list[string] | Eksik bilginin açıklaması                 |
| requires_clarification |      boolean | Müşteriden bilgi istenecek mi             |

Critical missing information varsa quote üretilmez.

Bu durumda:

```text
result_type = clarification
```

---

## 10. Equipment Decision Schema

Equipment Decision Engine’in çıktısıdır.

Logical entity:

```text
EquipmentDecision
```

Alanlar:

| Field              |   Type | Description                          |
| ------------------ | -----: | ------------------------------------ |
| selected_equipment | string | Seçilen ekipman                      |
| reason             | string | Ana karar nedeni                     |
| confidence         | string | low / medium / high                  |
| source             | string | rule / customer_memory / ai / manual |
| explanation        | string | UI’da gösterilecek açıklama          |

Örnek ekipman değerleri:

```text
Tenteli / Curtainsider
Mega Trailer
Reefer
Kapalı Kasa / Box Trailer
Platform
Lowbed
Special ADR Equipment
```

---

## 11. Risk Assessment Schema

Risk Assessment Engine teknik risk motoru değil, Operational Risk Engine’dir.

Logical entity:

```text
RiskAssessment
```

Alanlar:

| Field                      |         Type | Description                   |
| -------------------------- | -----------: | ----------------------------- |
| risk_level                 |       string | green / yellow / red          |
| risk_reasons               | list[string] | Risk nedenleri                |
| requires_human_review      |      boolean | İnsan kontrolü gerekli mi     |
| requires_management_review |      boolean | Yönetim incelemesi gerekli mi |

Risk seviyeleri:

```text
green
→ quote_ready

yellow
→ quote_with_review

red
→ management_review
```

---

## 12. Supplier Quote Schema

MVP’de supplier quote simüle edilmektedir.

İleride gerçek supplier maili, portal veya API verisi ile doldurulacaktır.

Logical entity:

```text
SupplierQuote
```

Alanlar:

| Field          |     Type | Description                       |
| -------------- | -------: | --------------------------------- |
| supplier_name  |   string | Tedarikçi adı                     |
| cost_amount    |   number | Maliyet                           |
| currency       |   string | EUR / USD / TRY                   |
| transit_time   |   string | Transit süre                      |
| validity_date  |     date | Geçerlilik                        |
| equipment_type |   string | Supplier’ın uygun ekipmanı        |
| notes          |   string | Supplier notları                  |
| source         |   string | simulation / email / portal / api |
| received_at    | datetime | Fiyatın geldiği zaman             |

---

## 13. Customer Quote Schema

Müşteriye sunulacak satış fiyatı modelidir.

Logical entity:

```text
CustomerQuote
```

Alanlar:

| Field         |   Type | Description                                      |
| ------------- | -----: | ------------------------------------------------ |
| supplier_cost | number | Tedarikçi maliyeti                               |
| markup_type   | string | `percentage`, `fixed` veya `manual` fiyat yöntemi |
| markup_value  | number | Maliyet üzerine uygulanan markup değeri          |
| final_price   | number | Yukarı yönde 10 EUR'a yuvarlanmış satış fiyatı  |
| currency      | string | Para birimi                                      |

Legacy `margin_type` ve `margin_value` constructor input'ları geçiş uyumluluğu
için kabul edilir; serialized model alanları markup terminolojisini kullanır.

---

## 14. Cost Item Schema

İleride detaylı fiyat kırılımı için kullanılacaktır.

Logical entity:

```text
CostItem
```

Alanlar:

| Field     |    Type | Description                                          |
| --------- | ------: | ---------------------------------------------------- |
| name      |  string | Maliyet adı                                          |
| amount    |  number | Tutar                                                |
| currency  |  string | Para birimi                                          |
| category  |  string | freight / local / surcharge / insurance / dg / other |
| mandatory | boolean | Zorunlu mu                                           |
| notes     |  string | Açıklama                                             |

Örnek cost item değerleri:

```text
Navlun
Fuel surcharge
Pickup
Delivery
Liman masrafları
Ordino
DG masrafı
Sigorta
```

---

## 15. Generated Draft Schema

Workflow sonucuna göre farklı draft üretilebilir.

Logical entity:

```text
GeneratedDraft
```

Alanlar:

| Field          |     Type | Description                               |
| -------------- | -------: | ----------------------------------------- |
| draft_type     |   string | quote / clarification / management_review |
| subject        |   string | Mail konusu                               |
| body           |     text | Draft gövdesi                             |
| recipient_type |   string | customer / internal                       |
| language       |   string | tr / en                                   |
| created_at     | datetime | Oluşturulma zamanı                        |

Aynı workflow sonucunda yalnızca ilgili ana draft kullanılmalıdır.

---

## 16. Action Recommendation Schema

Action Recommendation Engine, kullanıcıya bir sonraki aksiyonu gösterir.

Logical entity:

```text
ActionRecommendation
```

Alanlar:

| Field       |         Type | Description                                                                   |
| ----------- | -----------: | ----------------------------------------------------------------------------- |
| action_type |       string | quote_ready / quote_with_review / clarification / management_review / unknown |
| priority    |       string | normal / medium / high                                                        |
| title       |       string | UI başlığı                                                                    |
| explanation |       string | Açıklama                                                                      |
| checklist   | list[string] | Operasyon personeli için yapılacaklar                                         |
| source      |       string | workflow / risk / missing_info                                                |

---

## 17. Workflow Result Schema

`process_shipment()` fonksiyonunun ana çıktısıdır.

Logical entity:

```text
WorkflowResult
```

Alanlar:

| Field                   |                     Type | Description                               |
| ----------------------- | -----------------------: | ----------------------------------------- |
| result_type             |                   string | quote / clarification / management_review |
| shipment                |                 Shipment | Normalize edilmiş shipment                |
| customer_memory         |     CustomerMemoryResult | Müşteri hafızası sonucu                   |
| missing_info            | MissingInformationResult | Eksik bilgi sonucu                        |
| equipment_decision      |        EquipmentDecision | Ekipman kararı                            |
| risk_assessment         |           RiskAssessment | Risk kararı                               |
| supplier_quote          |     SupplierQuote / null | Tedarikçi fiyatı                          |
| customer_quote          |     CustomerQuote / null | Satış fiyatı                              |
| quote_draft             |    GeneratedDraft / null | Teklif draftı                             |
| clarification_draft     |    GeneratedDraft / null | Eksik bilgi draftı                        |
| management_review_draft |    GeneratedDraft / null | Yönetici inceleme draftı                  |
| action_recommendation   |     ActionRecommendation | Sonraki aksiyon                           |

---

## 18. Test Case Schema

Automated test suite için kullanılır.

Current storage:

```text
src/simulation/ai_email_test_cases.py
```

Logical entity:

```text
AITestCase
```

Alanlar:

| Field    |   Type | Description              |
| -------- | -----: | ------------------------ |
| name     | string | Test adı                 |
| email    |   text | Test müşteri maili       |
| expected |   dict | Beklenen workflow sonucu |

Expected alanında kontrol edilen başlıca değerler:

```text
result_type
selected_equipment
shipment_type
risk_level
customer_memory_matched
action_type
missing_fields
```

---

## 19. Customer Memory Export Schema

Export endpoint çıktısı:

```text
GET /customer-memory/export
```

Schema:

| Field         |                        Type | Description             |
| ------------- | --------------------------: | ----------------------- |
| export_type   |                      string | customer_memory         |
| profile_count |                      number | Profil sayısı           |
| profiles      | list[CustomerMemoryProfile] | Export edilen profiller |

---

## 20. Customer Memory Import Validation Schema

Import validation endpoint çıktısı:

```text
POST /customer-memory/import/validate
```

Schema:

| Field             |         Type | Description                          |
| ----------------- | -----------: | ------------------------------------ |
| valid             |      boolean | Import formatı geçerli mi            |
| profile_count     |       number | Profil sayısı                        |
| customer_names    | list[string] | Dosyadaki müşteri isimleri           |
| errors            | list[string] | Import’u engelleyen hatalar          |
| warnings          | list[string] | Uyarılar                             |
| duplicate_names   | list[string] | Dosya içi tekrar eden müşteri adları |
| duplicate_aliases | list[string] | Dosya içi tekrar eden aliaslar       |
| reserved_warnings | list[string] | Reserved term uyarıları              |

---

## 21. Customer Memory Import Dry Run Schema

Import dry run endpoint çıktısı:

```text
POST /customer-memory/import/dry-run
```

Schema:

| Field                 |         Type | Description                         |
| --------------------- | -----------: | ----------------------------------- |
| valid                 |      boolean | Dry run yapılabilir mi              |
| profile_count         |       number | Import dosyasındaki profil sayısı   |
| current_profile_count |       number | Mevcut sistemdeki profil sayısı     |
| new_profiles          | list[string] | Yeni profiller                      |
| existing_profiles     | list[string] | Mevcut profiller                    |
| name_conflicts        |   list[dict] | İleride kullanılacak conflict alanı |
| alias_conflicts       |   list[dict] | Başka müşteriye çakışan aliaslar    |
| will_add              | list[string] | Eklenecek profiller                 |
| will_update           | list[string] | Güncellenecek profiller             |
| will_skip             |   list[dict] | Atlanacak kayıtlar                  |
| errors                | list[string] | Hatalar                             |
| warnings              | list[string] | Uyarılar                            |

---

## 22. Backup File Schema

Customer Memory backup dosyaları şu klasörde tutulur:

```text
data/backups/
```

Dosya formatı:

```text
list[CustomerMemoryProfile]
```

Dosya adı formatı:

```text
customer_memory_backup_<timestamp>.json
```

---

## 23. Backup List Schema

Backup list endpoint çıktısı:

```text
GET /customer-memory/backups
```

Schema:

| Field   |                 Type | Description      |
| ------- | -------------------: | ---------------- |
| backups | list[BackupMetadata] | Backup dosyaları |

BackupMetadata:

| Field       |   Type | Description                  |
| ----------- | -----: | ---------------------------- |
| file_name   | string | Dosya adı                    |
| path        | string | Dosya yolu                   |
| size_bytes  | number | Dosya boyutu                 |
| modified_at | number | Dosya modification timestamp |

---

## 24. Restore Result Schema

Restore endpoint çıktısı:

```text
POST /customer-memory/backups/restore
```

Schema:

| Field                          |         Type | Description                       |
| ------------------------------ | -----------: | --------------------------------- |
| success                        |      boolean | Restore başarılı mı               |
| message                        |       string | Sonuç mesajı                      |
| result.restored_from           |       string | Restore edilen backup dosyası     |
| result.pre_restore_backup_path |       string | Restore öncesi alınan yeni backup |
| result.restored_profile_count  |       number | Restore edilen profil sayısı      |
| result.restored_profiles       | list[string] | Restore edilen müşteri adları     |

---

## 25. Backup Cleanup Preview Schema

Cleanup preview endpoint çıktısı:

```text
GET /customer-memory/backups/cleanup-preview
```

Schema:

| Field                   |                 Type | Description                   |
| ----------------------- | -------------------: | ----------------------------- |
| total_backup_count      |               number | Toplam backup sayısı          |
| keep_latest             |               number | Saklanacak son backup sayısı  |
| keep_count              |               number | Korunacak dosya sayısı        |
| cleanup_candidate_count |               number | Silmeye aday dosya sayısı     |
| backups_to_keep         | list[BackupMetadata] | Korunacak backup dosyaları    |
| cleanup_candidates      | list[BackupMetadata] | Silmeye aday backup dosyaları |
| cleanup_enabled         |              boolean | Preview aşamasında false      |
| message                 |               string | Açıklama                      |

---

## 26. Backup Cleanup Apply Schema

Cleanup apply endpoint çıktısı:

```text
POST /customer-memory/backups/cleanup
```

Schema:

| Field         |         Type | Description                       |
| ------------- | -----------: | --------------------------------- |
| success       |      boolean | Cleanup başarılı mı               |
| keep_latest   |       number | Korunan son backup sayısı         |
| deleted_count |       number | Silinen dosya sayısı              |
| failed_count  |       number | Silinemeyen dosya sayısı          |
| deleted_files | list[string] | Silinen dosyalar                  |
| failed_files  |   list[dict] | Silinemeyen dosyalar ve nedenleri |
| message       |       string | Sonuç mesajı                      |

---

## 27. Future Database Tables

İleride gerçek database’e geçildiğinde önerilen tablolar:

```text
customers
customer_memory_profiles
customer_memory_audit_logs
shipments
shipment_events
equipment_decisions
risk_assessments
missing_information_checks
supplier_quotes
customer_quotes
generated_drafts
action_recommendations
workflow_results
test_runs
test_run_results
backup_files
```

---

## 28. Data Sensitivity Policy

Customer Memory verisi operasyonel varsayımlar içerir.

Bu nedenle:

* müşteri gizli bilgileri gereksiz yere saklanmaz
* kişisel veri minimum düzeyde tutulur
* müşteri hafızası CRM yerine operasyonel karar desteği olarak kullanılır
* export / import / restore işlemleri dikkatli yönetilir
* backup dosyaları repository’ye commit edilmemelidir

---

## 29. Current Storage Policy

MVP aşamasında storage yaklaşımı:

```text
Customer Memory
→ data/customer_memory.json

Customer Memory Backups
→ data/backups/

Test Cases
→ Python source file

Runtime Workflow Results
→ API response only
```

İleride database’e geçilene kadar bu yapı korunur.

---

## 30. Next Schema Priorities

Sonraki schema geliştirme alanları:

* Supplier Profile schema
* Supplier Route Capability schema
* Supplier Score schema
* Rate Sheet schema
* Cost Breakdown schema
* Margin Rule schema
* Booking schema
* Document Checklist schema
