# UI Completion Phase — 2026-09-04

Bu belge, daha önce verilmiş ürün kararlarını tek bir browser UI tamamlama fazında uygulamak için çalışma checklist'idir.

## Çalışma kuralı
- Daha önce konuşulmuş ekran/akış kararları yeniden onay istenmeden uygulanır.
- Kritik olmayan yeni ürün kararları `Karar Parkı`na yazılır ve geliştirmeyi durdurmaz.
- Güvenlik, yetki, para/teklif otoritesi veya geri dönüşü zor veri modeli kararı gerçekten bloklarsa kullanıcıya dönülür.
- Canlı `main` bu faz tamamlanıp PR merge onayı verilene kadar değiştirilmez.

## Uygulanacaklar
- [x] Global shell: aktif menü durumu, tutarlı başlık/alt başlık, loading/empty/error davranışı, responsive polish.
- [x] Ana ekran: 3/5 günlük operasyon takvimi, dikkat alanı, yoğunluk davranışı.
- [x] MINA işleri listesi: daha okunur arama/filtre/özet ve dar ekran davranışı.
- [x] MINA iş detayı: yoğun ama bölümlenmiş operasyon görünümü; shipment/quote/supplier/operation/timeline ayrımı.
- [x] İş bazlı otomasyon override'ı: supplier reminder ve customer deadline update için inherit/manual/approval/automatic + mevcut legacy disable desteği.
- [x] Supplier follow-up: güvenli reminder preview + “şimdi hatırlat” akışı; approval-required ise mevcut approval boundary korunur.
- [x] Teklif alanı: quote özeti, pending approval için sade karar ekranı, approved quote için final output/gönderim yüzeyi.
- [x] Kritik onay/gönder ekranları: düşük dikkat dağıtıcı yoğunluk; inline red nedeni; browser prompt kullanılmaması.
- [x] Operasyon özeti: mevcut execution ve exception kanıtlarını daha okunur yoğun görünümde sunma.
- [x] İş Kuyruğu: self-claim, acknowledge, renew, takeover, release.
- [x] Raporlar: operator first-look performance dahil backend-authoritative read model.
- [x] Ayarlar: Branding yanında ajans genel otomasyon policy bölümü.
- [x] Branding: firma adı/logo/ana renk/vurgu rengi ve güvenli türetilmiş tonlar.
- [x] Regresyon: mevcut P2 shell testleri + yeni completion regression + canonical pilot gate.
- [x] Dolu/boş/responsive browser preview kontrolü.

## Karar Parkı
- Yöneticinin başka bir operatöre doğrudan iş ataması: operator directory + yetki modeli gerektirir; bu fazda self-claim korunur.
- İlk-bakış / aksiyon tamamlama SLA eşikleri: açık policy kararı olmadan yüzde üretilmez.
- Rol bazlı menü ve mutasyon yetkileri: mevcut tek-role pilot varsayımı korunur; yeni role modeli bu fazda icat edilmez.
- Supplier bazlı kalıcı reminder override: mevcut iş-geneli override korunur; supplier-level persistent ayar ayrı ürün kararıdır.
- “Operasyonu Başlat” butonunun tam yan etkisi: mevcut stage endpoint yalnız lifecycle geçişi yapıyor; ilk supplier send/timer başlatma semantiği ayrı backend orkestrasyonu gerektiriyorsa bunu UI butonuyla taklit etmeyeceğiz.
- Müşteri-bazlı otomasyon policy düzenleme ekranının yeri: backend authority mevcut, fakat ayrı müşteri master/browser workspace kararı bu fazın kapsamını aşar; ajans + iş override akışı tamamlanır.

## Karar Parkı Sonuçları — 2026-09-07

Önceki karar parkındaki ana maddeler kullanıcıyla birlikte kapatıldı ve P2-14 küçük-acenta operasyon fazına alındı:

- `Operasyonu Başlat`: müşteri kabulü + seçilmiş tedarikçi + kabul edilmiş tedarikçi fiyatından sonra çalışır; seçilen tedarikçiye tek onay/toplama maili ve araç bilgisi talebi, fiyat veren diğerlerine nazik kapanış üretir.
- Doğrudan operatör atama: aktif login kullanıcıları basit operatör dizinidir; kişi→kişi atama audit generation ile yapılır, rol hiyerarşisi eklenmez.
- Müşteri otomasyon istisnaları: Ayarlar→Otomasyon içinde kalır; ayrı büyük müşteri yönetim ekranı gerekmez.
- Tedarikçi bazlı kalıcı ayarlar: karayolu tedarikçi ilişkilerinin değişkenliği nedeniyle zengin supplier relationship profile temel ürün özelliğidir; geçmiş supplier yazışma/yanıtları MINAI için öneri kaynağıdır.
- Performans: tek personel puanı yoktur; ilk bakış, karar ve operasyon milestone gerçek süreleri, ortalama/medyan/P90 ve açıkça tanımlanmış hedefler raporlanır.

## P2-15 İlişki Hafızası — 2026-09-07

- [x] Ayarlar içine ayrı `İlişki Hafızası` sekmesi; sayfa açılışı mailbox geçmişini okumaz.
- [x] Tarih aralığı, mesaj sınırı ve açık yetki onayıyla kontrollü Outlook geçmiş analizi.
- [x] Inbox + Sent Items üzerinden müşteri ve tedarikçi için iki yönlü cevap süresi/iletişim kanıtı.
- [x] Master-data ile deterministik taraf eşleştirmesi; eşleşmeyen/çakışan adreslerde otomatik sınıflandırma yok.
- [x] Ham geçmiş mail gövdeleri kalıcı onboarding state'ine yazılmaz.
- [x] Deterministik ilişki metrikleri ile AI davranış gözlemleri ayrı kaynaklar olarak üretilir.
- [x] AI analizi ayrı opt-in; yalnız privacy-transformed `PrivacySafeText` kullanır.
- [x] Tüm yeni gözlemler mevcut LearningFact review akışında `proposed` başlar; doğrula/reddet UI'ı korunur.
- [x] Onaylı bilgi değişiyorsa sessiz overwrite yerine replacement proposal üretilir.
- [x] Normal günlük Outlook pull limiti ve ingestion davranışı değiştirilmez.
