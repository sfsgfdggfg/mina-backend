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


DEC-019
Customer = Company

Contact Person ≠ Customer

DEC-020
Public email domainleri müşteri tanımlamada company domain olarak kullanılmaz.

Örnek:
gmail.com
hotmail.com
outlook.com
yahoo.com
icloud.com

DEC-021

Customer Recognition Engine
çok katmanlı çalışacaktır.

Öncelik sırası:

1. Known Contact
2. Company Domain
3. Email Signature
4. Historical Email Context
5. Manual Assignment


DEC-022

Knowledge Capture Phase tamamlanmıştır.

Yeni özellik ekleme geçici olarak durdurulur.

Öncelik:
Database Schema
Workflow Engine
MVP Architecture

[DEC-023 REVISION]

Historical Pricing Intelligence
MVP kapsamına dahil değildir.

Ancak gelecekte kullanılmak üzere
fiyat geçmişi saklanacaktır.
