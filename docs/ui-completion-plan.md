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
