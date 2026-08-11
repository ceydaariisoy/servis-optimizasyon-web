# Servis Rota Optimizasyonu — Web Sürümü

Bu proje, çalışan adres Excel'ini yükleyerek kapasite kısıtlı servis rotaları üretir.
Bilgisayara Python kurmak gerekmez; Streamlit Community Cloud üzerinde tarayıcıdan çalışır.

## Özellikler

- Mevcut **3 servis** veya **otomatik minimum servis sayısı** seçimi
- Tüm araçlar için ortak kapasite sınırı
- Sabah (çalışan → fabrika) ve akşam (fabrika → çalışan) yönü
- Aktif olmayan veya servis kullanmayan çalışanları dışarıda bırakma
- Yeni çalışan eklendiğinde ya da çalışan ayrıldığında güncel Excel ile yeniden hesaplama
- Eksik koordinatları ücretsiz Nominatim servisiyle tamamlama; API anahtarı gerekmez
- OSRM yol süreleri; erişim olmazsa yaklaşık mesafeye otomatik geçiş
- Harita, rota sırası, süre, mesafe, doluluk ve Excel sonuç indirme

## İnternette yayınlama

1. Bu klasördeki tüm dosyaları yeni bir GitHub deposuna yükleyin.
2. `share.streamlit.io` adresini açıp GitHub hesabınızla giriş yapın.
3. **Create app** seçeneğine basın.
4. Depoyu seçin; ana dosya yolu olarak `app.py` yazın.
5. **Deploy** düğmesine basın.

Uygulama birkaç dakika içinde `...streamlit.app` uzantılı bir bağlantı verir. Bu bağlantıyı başka
kişilerle paylaşabilirsiniz. Bağımlılıklar `requirements.txt` dosyasından otomatik kurulur.

## Excel kullanımı

`Servis_Veri_Sablonu.xlsx` dosyasını açın ve satırları güncelleyin. Önerilen sütunlar:

- `Personel_Sicil`
- `Ad_Soyad`
- `Tip` (`Ofis/Fabrika` veya `Çalışan`)
- `Adres`
- `Enlem`
- `Boylam`
- `Aktif_mi` (`Evet/Hayır`)
- `Servis_Kullaniyor_mu` (`Evet/Hayır`)

Enlem ve boylam biliniyorsa doğrudan yazılması daha güvenilirdir. Boş bırakılırsa uygulamadaki
**Eksik koordinatları adresten bul** düğmesi kullanılabilir. Fabrika koordinatları gerçek konumla
değiştirilmelidir.

## Önemli not

Bu çıktı operasyonel karar için bir **taslak rota planıdır**. Servis başlamadan önce yol yasakları,
tek yönler, gerçek durak güvenliği, vardiya saati ve trafik koşulları operasyon ekibi tarafından
kontrol edilmelidir.

