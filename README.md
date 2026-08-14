# Servis Rota Optimizasyonu — Web Sürümü

Bu proje, çalışan adres Excel'ini yükleyerek kapasite kısıtlı servis rotaları üretir.
Bilgisayara Python kurmak gerekmez; Streamlit Community Cloud üzerinde tarayıcıdan çalışır.

## Özellikler

- Mevcut **3 servis** veya kapasite ve azami süreye göre **otomatik servis sayısı** seçimi
- Tüm araçlar için ortak kapasite sınırı
- OR-Tools ile mümkün olan en az ortak durak sayısı ve toplam yürüyüş optimizasyonu
- Durak talebi, araç kapasitesi, gerçek yol süresi ve rota sırasını birlikte çözen araç rotalama modeli
- Ayarlanabilir azami rota süresi ve durak başına bekleme süresi
- Sabah (çalışan → fabrika) ve akşam (fabrika → çalışan) yönü
- Aktif olmayan veya servis kullanmayan çalışanları dışarıda bırakma
- Yeni çalışan eklendiğinde ya da çalışan ayrıldığında güncel Excel ile yeniden hesaplama
- Eksik koordinatları ücretsiz Nominatim servisiyle tamamlama; API anahtarı gerekmez
- OSRM yol süreleri; erişim olmazsa yaklaşık mesafeye otomatik geçiş
- Harita, rota sırası, sürüş/toplam süre, mesafe, doluluk, tekil/ortak durak ve Excel sonuç indirme

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

Yürüyüş mesafesi, kuş uçuşu mesafeye şehir içi sapmaları temsil eden %20 güvenlik payı
eklenerek tahmin edilir. Bu çıktı güçlü bir optimizasyon planıdır; yine de servis başlamadan önce
yol yasakları, gerçek durak güvenliği, kaldırım/yaya geçidi, vardiya saati ve trafik koşulları
operasyon ekibi tarafından kontrol edilmelidir.
