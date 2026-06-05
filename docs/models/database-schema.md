# MINAI Freight OS

# Database Schema v1

## Purpose

Bu doküman MINAI Freight OS’un ilk MVP veri modelini tanımlar.

MVP kapsamı:

* Email → Quote
* Road Freight odaklı
* Semi-auto çalışma
* İnsan onaylı teklif gönderimi
* Customer Intelligence
* Supplier Intelligence
* Risk Assessment
* Equipment Decision
* Quote Drafting

---

# 1. Core Design Principles

## 1.1 Customer = Company

Müşteri kişi değil, şirkettir.

Örnek:

* [selman@temsa.com](mailto:selman@temsa.com)
* [ayse@temsa.com](mailto:ayse@temsa.com)
* [mehmet@temsa.com](mailto:mehmet@temsa.com)

hepsi aynı `customer` kaydına bağlı olabilir.

---

## 1.2 Contact Person ≠ Customer

Kişiler `customer_contacts` tablosunda tutulur.

Her kişi bir müşteriye bağlıdır.

---

## 1.3 Public Email Domains Are Not Company Domains

Aşağıdaki domainler müşteri şirket domain’i olarak kullanılmaz:

* gmail.com
* hotmail.com
* outlook.com
* yahoo.com
* icloud.com

Bu domainlerden gelen maillerde sistem müşteri eşleştirmesini:

1. Bilinen kontak
2. Mail imzası
3. Geçmiş yazışma
4. Manuel kullanıcı eşleştirmesi

ile yapar.

---

## 1.4 Shipment Is the Operational Core

Her müşteri talebi bir `shipment` kaydına dönüşür.

Shipment kaydı:

* müşteri
* kontak kişi
* yükleme bilgileri
* teslimat bilgileri
* ürün bilgisi
* ekipman kararı
* risk seviyesi
* teklif durumu

bilgilerini taşır.

---

## 1.5 Quote History Is Stored but Not Used for Automatic Pricing in MVP

Geçmiş fiyatlar saklanır.

MVP v1’de geçmiş fiyatlar:

* otomatik fiyat üretmek için kullanılmaz
* referans / benchmark / anomali kontrolü için ileride kullanılabilir

---

# 2. Tables Overview

MVP v1 için ana tablolar:

* customers
* customer_contacts
* customer_domains
* customer_locations
* customer_products
* suppliers
* supplier_contacts
* supplier_routes
* supplier_capabilities
* supplier_scores
* emails
* shipments
* shipment_packages
* shipment_risks
* supplier_quotes
* customer_quotes
* quote_drafts
* audit_logs

---

# 3. customers

Müşteri şirket kayıtları.

| Field             | Type      | Description                 |
| ----------------- | --------- | --------------------------- |
| id                | UUID      | Primary key                 |
| company_name      | TEXT      | Şirket adı                  |
| company_code      | TEXT      | Kısa kod / internal code    |
| industry          | TEXT      | Sektör                      |
| country           | TEXT      | Ana ülke                    |
| default_language  | TEXT      | TR / EN vb.                 |
| price_sensitivity | TEXT      | low / medium / high         |
| time_sensitivity  | TEXT      | low / medium / high         |
| customer_status   | TEXT      | active / passive / prospect |
| notes             | TEXT      | Operasyonel notlar          |
| created_at        | TIMESTAMP | Oluşturma tarihi            |
| updated_at        | TIMESTAMP | Güncelleme tarihi           |

---

# 4. customer_contacts

Müşteri firmaya bağlı kişiler.

| Field                  | Type      | Description        |
| ---------------------- | --------- | ------------------ |
| id                     | UUID      | Primary key        |
| customer_id            | UUID      | FK → customers.id  |
| name                   | TEXT      | Kişi adı           |
| email                  | TEXT      | Mail adresi        |
| email_local_part       | TEXT      | @ öncesi kısım     |
| email_domain           | TEXT      | Mail domain        |
| is_public_email_domain | BOOLEAN   | Gmail/Hotmail vb.  |
| title                  | TEXT      | Ünvan              |
| phone                  | TEXT      | Telefon            |
| is_primary_contact     | BOOLEAN   | Ana kontak mı      |
| recognition_confidence | FLOAT     | Tanıma güven skoru |
| created_at             | TIMESTAMP | Oluşturma tarihi   |
| updated_at             | TIMESTAMP | Güncelleme tarihi  |

Example:

```text
email: selman@temsa.com
email_local_part: selman
email_domain: temsa.com
customer_id: TEMSA
```

---

# 5. customer_domains

Şirket domain kayıtları.

| Field       | Type      | Description             |
| ----------- | --------- | ----------------------- |
| id          | UUID      | Primary key             |
| customer_id | UUID      | FK → customers.id       |
| domain      | TEXT      | temsa.com, temsa.com.tr |
| is_verified | BOOLEAN   | Doğrulandı mı           |
| created_at  | TIMESTAMP | Oluşturma tarihi        |

Important:

Public domainler bu tabloda tutulmaz.

---

# 6. customer_locations

Müşterinin düzenli yükleme / teslimat adresleri.

| Field               | Type      | Description                                 |
| ------------------- | --------- | ------------------------------------------- |
| id                  | UUID      | Primary key                                 |
| customer_id         | UUID      | FK → customers.id                           |
| location_name       | TEXT      | Fabrika, depo, merkez vb.                   |
| location_type       | TEXT      | factory / warehouse / office / port / other |
| country             | TEXT      | Ülke                                        |
| city                | TEXT      | Şehir                                       |
| area                | TEXT      | OSB / bölge                                 |
| postcode            | TEXT      | Posta kodu                                  |
| address_text        | TEXT      | Açık adres                                  |
| is_default_pickup   | BOOLEAN   | Varsayılan yükleme adresi                   |
| is_default_delivery | BOOLEAN   | Varsayılan teslim adresi                    |
| usage_frequency     | INTEGER   | Kullanım sıklığı                            |
| notes               | TEXT      | Operasyonel not                             |
| created_at          | TIMESTAMP | Oluşturma tarihi                            |
| updated_at          | TIMESTAMP | Güncelleme tarihi                           |

---

# 7. customer_products

Müşterinin düzenli taşıttığı ürünler.

| Field                    | Type      | Description                      |
| ------------------------ | --------- | -------------------------------- |
| id                       | UUID      | Primary key                      |
| customer_id              | UUID      | FK → customers.id                |
| product_name             | TEXT      | Ürün adı                         |
| product_category         | TEXT      | Gıda, tekstil, makine vb.        |
| typical_weight_min       | FLOAT     | Tipik minimum ağırlık            |
| typical_weight_max       | FLOAT     | Tipik maksimum ağırlık           |
| typical_dimensions_text  | TEXT      | Tipik ölçü açıklaması            |
| default_equipment_type   | TEXT      | Tenteli, kapalı kasa, reefer vb. |
| is_adr                   | BOOLEAN   | ADR bilgisi                      |
| is_temperature_sensitive | BOOLEAN   | Sıcaklık hassasiyeti             |
| is_fragile               | BOOLEAN   | Hassas ürün                      |
| confidence_score         | FLOAT     | Bu bilginin güven skoru          |
| notes                    | TEXT      | Operasyonel not                  |
| created_at               | TIMESTAMP | Oluşturma tarihi                 |
| updated_at               | TIMESTAMP | Güncelleme tarihi                |

Example:

```text
Customer: Oğuz Gıda
Product: Meşrubat
Default Equipment: Kapalı Kasa
```

```text
Customer: Beta Enerji
Product: Elektrik Transformatörü
Default Equipment: Tenteli
```

---

# 8. suppliers

Tedarikçi / nakliyeci / acente kayıtları.

| Field         | Type      | Description                           |
| ------------- | --------- | ------------------------------------- |
| id            | UUID      | Primary key                           |
| company_name  | TEXT      | Tedarikçi adı                         |
| supplier_type | TEXT      | carrier / haulier / agent / forwarder |
| country       | TEXT      | Ülke                                  |
| active        | BOOLEAN   | Aktif mi                              |
| notes         | TEXT      | Operasyonel notlar                    |
| created_at    | TIMESTAMP | Oluşturma tarihi                      |
| updated_at    | TIMESTAMP | Güncelleme tarihi                     |

---

# 9. supplier_contacts

Tedarikçi kontak kişileri.

| Field              | Type      | Description                    |
| ------------------ | --------- | ------------------------------ |
| id                 | UUID      | Primary key                    |
| supplier_id        | UUID      | FK → suppliers.id              |
| name               | TEXT      | Kişi adı                       |
| email              | TEXT      | Mail                           |
| phone              | TEXT      | Telefon                        |
| role               | TEXT      | Pricing / operasyon / yönetici |
| is_primary_contact | BOOLEAN   | Ana kontak mı                  |
| created_at         | TIMESTAMP | Oluşturma tarihi               |

---

# 10. supplier_routes

Tedarikçilerin güçlü olduğu hatlar.

| Field               | Type      | Description       |
| ------------------- | --------- | ----------------- |
| id                  | UUID      | Primary key       |
| supplier_id         | UUID      | FK → suppliers.id |
| origin_country      | TEXT      | Çıkış ülkesi      |
| origin_region       | TEXT      | Bölge / şehir     |
| destination_country | TEXT      | Varış ülkesi      |
| destination_region  | TEXT      | Bölge / şehir     |
| service_type        | TEXT      | FTL / LTL         |
| priority_rank       | INTEGER   | Öncelik sırası    |
| active              | BOOLEAN   | Aktif mi          |
| notes               | TEXT      | Hat notları       |
| created_at          | TIMESTAMP | Oluşturma tarihi  |

Business Rule:

RFQ maksimum 3 tedarikçiye gönderilir.

Bu tablo supplier shortlist için kullanılır.

---

# 11. supplier_capabilities

Tedarikçi kabiliyetleri.

| Field         | Type    | Description       |
| ------------- | ------- | ----------------- |
| id            | UUID    | Primary key       |
| supplier_id   | UUID    | FK → suppliers.id |
| curtainsider  | BOOLEAN | Tenteli           |
| box_trailer   | BOOLEAN | Kapalı kasa       |
| reefer        | BOOLEAN | Frigorifik        |
| mega          | BOOLEAN | Mega dorse        |
| lowbed        | BOOLEAN | Lowbed            |
| open_trailer  | BOOLEAN | Açık kasa         |
| adr           | BOOLEAN | ADR               |
| heavy_lift    | BOOLEAN | Ağır yük          |
| project_cargo | BOOLEAN | Proje kargo       |
| express       | BOOLEAN | Express           |
| notes         | TEXT    | Notlar            |

---

# 12. supplier_scores

Tedarikçi performans skorları.

| Field                | Type      | Description        |
| -------------------- | --------- | ------------------ |
| id                   | UUID      | Primary key        |
| supplier_id          | UUID      | FK → suppliers.id  |
| operational_score    | FLOAT     | Operasyon kalitesi |
| commercial_score     | FLOAT     | Fiyat seviyesi     |
| relationship_score   | FLOAT     | İlişki / sadakat   |
| response_speed_score | FLOAT     | Cevap hızı         |
| on_time_score        | FLOAT     | Zamanında teslim   |
| damage_score         | FLOAT     | Hasarsızlık        |
| flexibility_score    | FLOAT     | Problem çözme      |
| last_updated         | TIMESTAMP | Güncelleme tarihi  |

Supplier selection sadece en düşük fiyat mantığıyla çalışmaz.

---

# 13. emails

Sisteme giren müşteri ve tedarikçi mailleri.

| Field               | Type      | Description              |
| ------------------- | --------- | ------------------------ |
| id                  | UUID      | Primary key              |
| external_email_id   | TEXT      | Outlook/Gmail message id |
| thread_id           | TEXT      | Mail thread id           |
| sender_email        | TEXT      | Gönderen                 |
| sender_name         | TEXT      | Gönderen adı             |
| subject             | TEXT      | Konu                     |
| body_text           | TEXT      | Mail içeriği             |
| received_at         | TIMESTAMP | Geliş zamanı             |
| direction           | TEXT      | inbound / outbound       |
| related_customer_id | UUID      | FK → customers.id        |
| related_supplier_id | UUID      | FK → suppliers.id        |
| related_shipment_id | UUID      | FK → shipments.id        |
| ai_processed        | BOOLEAN   | AI işledi mi             |
| created_at          | TIMESTAMP | Kayıt tarihi             |

---

# 14. shipments

Ana operasyon talebi.

| Field                     | Type      | Description                                                   |
| ------------------------- | --------- | ------------------------------------------------------------- |
| id                        | UUID      | Primary key                                                   |
| customer_id               | UUID      | FK → customers.id                                             |
| contact_id                | UUID      | FK → customer_contacts.id                                     |
| source_email_id           | UUID      | FK → emails.id                                                |
| transport_mode            | TEXT      | road / sea / air                                              |
| direction                 | TEXT      | import / export / cross_trade / unknown                       |
| service_type              | TEXT      | FTL / LTL / unknown                                           |
| pickup_country            | TEXT      | Yükleme ülkesi                                                |
| pickup_city               | TEXT      | Yükleme şehri                                                 |
| pickup_area               | TEXT      | OSB / bölge                                                   |
| pickup_postcode           | TEXT      | Posta kodu                                                    |
| pickup_address_text       | TEXT      | Açık adres                                                    |
| delivery_country          | TEXT      | Teslim ülkesi                                                 |
| delivery_city             | TEXT      | Teslim şehri                                                  |
| delivery_area             | TEXT      | Bölge                                                         |
| delivery_postcode         | TEXT      | Posta kodu                                                    |
| delivery_address_text     | TEXT      | Açık adres                                                    |
| commodity                 | TEXT      | Ürün cinsi                                                    |
| gross_weight              | FLOAT     | Brüt ağırlık                                                  |
| weight_is_approximate     | BOOLEAN   | Ağırlık yaklaşık mı                                           |
| piece_count               | INTEGER   | Parça adedi                                                   |
| equipment_type            | TEXT      | Tenteli, reefer, lowbed vb.                                   |
| equipment_confidence      | FLOAT     | Ekipman kararı güven skoru                                    |
| cargo_ready_date          | DATE      | Yük hazır tarihi                                              |
| required_delivery_date    | DATE      | Beklenen teslim tarihi                                        |
| incoterm                  | TEXT      | Zorunlu değil                                                 |
| is_adr                    | BOOLEAN   | ADR mi                                                        |
| adr_class                 | TEXT      | ADR sınıfı                                                    |
| is_temperature_controlled | BOOLEAN   | Sıcaklık kontrollü mü                                         |
| temperature_requirement   | TEXT      | +4 / -18 vb.                                                  |
| is_high_value             | BOOLEAN   | Yüksek değerli mi                                             |
| is_oversized              | BOOLEAN   | Gabari dışı mı                                                |
| is_heavy_single_piece     | BOOLEAN   | Tek parça ağır mı                                             |
| risk_level                | TEXT      | green / yellow / red                                          |
| status                    | TEXT      | new / parsed / rfq_sent / quoted / approved / sent / rejected |
| ai_confidence_score       | FLOAT     | Genel AI güven skoru                                          |
| created_at                | TIMESTAMP | Oluşturma tarihi                                              |
| updated_at                | TIMESTAMP | Güncelleme tarihi                                             |

---

# 15. shipment_packages

Yük parça ve ölçü detayları.

| Field        | Type    | Description                                     |
| ------------ | ------- | ----------------------------------------------- |
| id           | UUID    | Primary key                                     |
| shipment_id  | UUID    | FK → shipments.id                               |
| package_type | TEXT    | pallet / crate / machine / loose / roll / other |
| quantity     | INTEGER | Adet                                            |
| length_cm    | FLOAT   | Boy                                             |
| width_cm     | FLOAT   | En                                              |
| height_cm    | FLOAT   | Yükseklik                                       |
| weight_kg    | FLOAT   | Parça ağırlığı                                  |
| stackable    | BOOLEAN | İstiflenebilir mi                               |
| notes        | TEXT    | Not                                             |

---

# 16. shipment_risks

Shipment bazlı risk kayıtları.

| Field                      | Type      | Description                                |
| -------------------------- | --------- | ------------------------------------------ |
| id                         | UUID      | Primary key                                |
| shipment_id                | UUID      | FK → shipments.id                          |
| risk_code                  | TEXT      | RISK-001 vb.                               |
| risk_category              | TEXT      | customer / time / cargo / route / contract |
| risk_level                 | TEXT      | green / yellow / red                       |
| description                | TEXT      | Risk açıklaması                            |
| requires_human_review      | BOOLEAN   | İnsan onayı gerekli mi                     |
| requires_management_review | BOOLEAN   | Yönetim onayı gerekli mi                   |
| created_at                 | TIMESTAMP | Oluşturma tarihi                           |

---

# 17. supplier_quotes

Tedarikçilerden gelen fiyatlar.

| Field                | Type      | Description             |
| -------------------- | --------- | ----------------------- |
| id                   | UUID      | Primary key             |
| shipment_id          | UUID      | FK → shipments.id       |
| supplier_id          | UUID      | FK → suppliers.id       |
| source_email_id      | UUID      | FK → emails.id          |
| quoted_cost          | FLOAT     | Tedarikçi maliyeti      |
| currency             | TEXT      | EUR / USD / TRY         |
| transit_time_text    | TEXT      | Transit süre açıklaması |
| validity_date        | DATE      | Geçerlilik tarihi       |
| equipment_type       | TEXT      | Verilen ekipman         |
| includes_extra_costs | BOOLEAN   | Ek masraflar dahil mi   |
| notes                | TEXT      | Not                     |
| received_at          | TIMESTAMP | Fiyat geliş zamanı      |
| created_at           | TIMESTAMP | Kayıt zamanı            |

---

# 18. customer_quotes

Müşteriye oluşturulan teklif.

| Field                      | Type      | Description                                           |
| -------------------------- | --------- | ----------------------------------------------------- |
| id                         | UUID      | Primary key                                           |
| shipment_id                | UUID      | FK → shipments.id                                     |
| selected_supplier_quote_id | UUID      | FK → supplier_quotes.id                               |
| supplier_cost              | FLOAT     | Seçilen tedarikçi maliyeti                            |
| margin_type                | TEXT      | percentage / fixed / manual                           |
| margin_value               | FLOAT     | Kar değeri                                            |
| final_price                | FLOAT     | Müşteri satış fiyatı                                  |
| currency                   | TEXT      | EUR / USD / TRY                                       |
| validity_date              | DATE      | Teklif geçerlilik tarihi                              |
| quote_status               | TEXT      | draft / pending_approval / approved / sent / rejected |
| price_context_note         | TEXT      | Geçmiş fiyat / piyasa notu                            |
| created_at                 | TIMESTAMP | Oluşturma                                             |
| updated_at                 | TIMESTAMP | Güncelleme                                            |

---

# 19. quote_drafts

AI tarafından hazırlanan teklif maili taslakları.

| Field               | Type      | Description             |
| ------------------- | --------- | ----------------------- |
| id                  | UUID      | Primary key             |
| customer_quote_id   | UUID      | FK → customer_quotes.id |
| email_subject       | TEXT      | Mail konusu             |
| email_body          | TEXT      | Mail içeriği            |
| language            | TEXT      | TR / EN                 |
| ai_model            | TEXT      | Kullanılan model        |
| ai_confidence_score | FLOAT     | Güven skoru             |
| human_edited        | BOOLEAN   | İnsan düzenledi mi      |
| approved_by_user_id | UUID      | Onaylayan kullanıcı     |
| created_at          | TIMESTAMP | Oluşturma               |
| approved_at         | TIMESTAMP | Onay tarihi             |
| sent_at             | TIMESTAMP | Gönderim tarihi         |

---

# 20. audit_logs

Sistemde yapılan önemli aksiyonlar.

| Field        | Type      | Description                            |
| ------------ | --------- | -------------------------------------- |
| id           | UUID      | Primary key                            |
| entity_type  | TEXT      | shipment / quote / customer / supplier |
| entity_id    | UUID      | İlgili kayıt                           |
| action       | TEXT      | created / updated / approved / sent    |
| performed_by | TEXT      | ai / user                              |
| user_id      | UUID      | Kullanıcı id                           |
| description  | TEXT      | Açıklama                               |
| created_at   | TIMESTAMP | Tarih                                  |

---

# 21. Key Relationships

```text
customers
  └── customer_contacts
  └── customer_locations
  └── customer_products
  └── customer_domains

customers
  └── shipments

shipments
  └── shipment_packages
  └── shipment_risks
  └── supplier_quotes
  └── customer_quotes

suppliers
  └── supplier_contacts
  └── supplier_routes
  └── supplier_capabilities
  └── supplier_scores

customer_quotes
  └── quote_drafts
```

---

# 22. MVP Notes

MVP v1’de zorunlu olmayan ama veri yapısında kapısı açık bırakılan alanlar:

* historical pricing intelligence
* advanced supplier scoring
* automated pricing suggestions
* carrier portal integrations
* multi-modal transport
* sea freight
* air freight

---

# 23. Next Step

Bu schema onaylandıktan sonra sıradaki doküman:

```text
docs/models/workflow-engine.md
```

olacaktır.

Workflow Engine içinde:

* Customer Recognition Flow
* Shipment Extraction Flow
* Equipment Decision Flow
* Risk Assessment Flow
* Supplier Selection Flow
* Quote Draft Flow

tanımlanacaktır.

