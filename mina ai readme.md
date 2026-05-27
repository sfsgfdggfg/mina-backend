# 🚀 Project Minai (Internal AI-Driven Logistics Assistant)

Minai, uluslararası lojistik ve forwarder acentelerinin günlük operasyonel yükünü hafifletmek, gelen RFQ (Teklif Talebi) e-postalarını anlamlandırmak ve armatör portallarından otomatik fiyat çekerek teklif süreçlerini hızlandırmak için tasarlanmış yapay zeka tabanlı bir SaaS platformudur.

## 📌 Project Architecture & Vision

- **Core Product Brand:** Vitrinde ve asistan kişiliğinde "Mina" veya "Mina AI" ismi kullanılacaktır. Resmi tescil ve marka süreçleri "Minai" / "MinaOps" olarak yürütülecektir.
- **UI/UX Design Language:** TNT Turuncusu aksan renkleri ile yapılandırılmış modern, karanlık mod (Dark Mode) ağırlıklı, 3 kolonlu dashboard mimarisi.
- **Repository Management:** Fikri mülkiyet ve ticari sırların korunması amacıyla bu depo tamamen "Private" (Gizli) olarak tutulacaktır. Technical Lead (CTO) olarak kod kontrolü Demir'dedir.

---

## 🛠️ Phase 1: MVP (Minimum Viable Product) Scope

Faz 1 kapsamında sistemin temel lojistik refleksleri ve otomasyon altyapısı ayağa kaldırılacaktır:

### 1. E-Mail Parsing & Intelligence (E-Posta Veri Ayıklama)
- Gelen forwarder ve müşteri e-postalarındaki düzensiz metinlerin taranması.
- LLM API'leri kullanılarak şu kritik lojistik parametrelerinin hatasız ayıklanması ve JSON objesine dönüştürülmesi:
  - **POL** (Port of Loading - Yükleme Limanı)
  - **POD** (Port of Discharge - Tahliye Limanı)
  - **Volume/Equipment** (Konteyner tipi ve adedi: 20DC, 40HC, Reefer vb.)
  - **Commodity** (Yük cinsi: FAK, Hazmat vb.)

### 2. Live Freight Scraping / RPA (Canlı Navlun Kazıma)
- Ayıklanan liman ve hacim bilgileri kullanılarak taşıyıcı (MSC vb.) portallarına arka planda otomatik sorgu atılması.
- Güncel navlun, lokal masraflar ve geçerlilik tarihlerinin canlı olarak çekilmesi.

### 3. Action Dashboard & PDF Generation (Onay Paneli ve Teklif)
- Çekilen fiyatların operasyon personelinin önüne 3 kolonlu temiz bir arayüzle düşürülmesi.
- Personel onayından sonra şablonu hazır, kurumsal bir PDF teklif dosyasının otomatik üretilmesi.

---

## 🪙 Infrastructure & Budget Projections (Initial Phase)

Sistemin ilk aşamada ayakta kalması için kullanılacak maliyet ve performans odaklı bulut mimarisi:

- **Hosting & Infrastructure:** 
  - Vitrin Sitesi: Hostinger / Güzel Hosting (Yıllık ~1.000 - 3.000 TL)
  - Uygulama Sunucusu: DigitalOcean / Linode VPS (Aylık ~$6 - $12)
- **AI Stack (Model Agnostic Architecture):**
  - Standart ve kısa mailler için hız/maliyet odaklı: `gpt-4o-mini` (OpenAI API)
  - PDF ekli, karmaşık ve uzun RFQ'lar için zeka odaklı: `claude-3-5-sonnet` (Anthropic API)
  - Veri Gizliliği: API seviyesinde veri saklanmama (Zero Data Retention) politikası zorunludur.

---

## 📈 Dev Roadmap / Next Steps

1. [ ] Demir tarafından GitHub deposunun "Private" olarak ilklendirilmesi (Initialize).
2. [ ] Python (FastAPI) veya Node.js tabanlı temel backend iskeletinin kurulması.
3. [ ] OpenAI API bağlantısının ve lojistik veri modeli şemalarının (JSON Schema) çıkarılması.
4. [ ] E-posta entegrasyonu (IMAP/Webhook) altyapısının kodlanması.

---
*This document serves as the single source of truth for Project Minai's development cycle.*