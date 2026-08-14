# Literatür Uyumlu Servis Rota Optimizasyonu

Bu proje, çalışan adres Excel'ini yükleyerek ortak durakları ve kapasite kısıtlı
servis rotalarını birlikte üretir.
Bilgisayara Python kurmak gerekmez; Streamlit Community Cloud üzerinde tarayıcıdan çalışır.

Uygulanan problem sınıfı **durak seçimi içeren okul/personel servisi rotalama**dır
(School Bus Routing Problem with Bus Stop Selection — SBRP-BSS). Bu sınıf,
çalışanları önce bağımsız kümelere ayırıp sonra rota çizmek yerine aday durak seçimi,
çalışan-durak ataması ve araç rotalamayı aynı planlama zincirinde ele alır.

## Özellikler

- Mevcut **3 servis** veya kapasite ve azami süreye göre **otomatik servis sayısı** seçimi
- Tüm araçlar için ortak kapasite sınırı
- Çalışan adresleri, otomatik ortak ara noktalar ve yüklenen mevcut/adayı duraklardan aday kümesi
- CP-SAT set-cover modeliyle tüm çalışanları kapsayan **teorik minimum durak sayısı**
- Minimum durak ile çalışan konforu arasında ayarlanabilir **hedef ortalama yürüme** dengesi
- Her çalışanın tam bir durağa atanması ve azami yürüme sınırının korunması
- OR-Tools ile durak talebi, araç kapasitesi, gerçek yol süresi ve rota sırasını birlikte çözen araç rotalama modeli
- Ayarlanabilir azami rota süresi ve durak başına bekleme süresi
- Sabah (çalışan → fabrika) ve akşam (fabrika → çalışan) yönü
- Aktif olmayan veya servis kullanmayan çalışanları dışarıda bırakma
- Yeni çalışan eklendiğinde ya da çalışan ayrıldığında güncel Excel ile yeniden hesaplama
- Günlük değişiklikler için önceki durak ve rota sırasını koruyan **artımlı güncelleme modu**
- Yeni çalışanı önce erişilebilir mevcut durağa ekleme; yalnızca gerekirse yeni durak veya araç açma
- **Yalnızca yüklenen duraklar** ya da **yüklenen + saha onayına sunulacak otomatik adaylar** politikası
- OSRM yol süreleri; erişim olmazsa yaklaşık mesafeye otomatik geçiş
- Harita, rota sırası, sürüş/toplam süre, mesafe, doluluk, tekil/ortak durak ve Excel sonuç indirme

## Modelin aşamaları

1. Aday duraklar üretilir. Çalışan evleri her zaman yedek adaydır; birbirine yakın
   ev çiftlerinin orta noktaları ortak durak adayı olur. Mevcut/adayı durak dosyası varsa
   bu noktalar öncelikli aday olarak eklenir.
2. CP-SAT set-cover modeli, her çalışan azami yürüme sınırındaki en az bir durakla
   kapsanacak şekilde teorik minimum durak sayısını bulur.
3. Ortalama yürüyüş seçilen hedefin üzerindeyse en çok yürüme iyileştirmesi sağlayan
   duraklar eklenir. Böylece salt minimum durak çözümünün çalışanlara gereksiz yük
   bindirmesi önlenir.
4. Seçilen durakların yolcu talepleriyle kapasite ve azami rota süresi kısıtlı açık
   araç rotalama modeli çözülür. Otomatik mod, kapasite alt sınırından başlayarak süre
   kısıtı gerekirse araç ekler.

Bu yapı, Schittekat vd. (2013) tarafından ele alınan SBRP-BSS yaklaşımıyla ve çalışan
servisi için durak kapsama, kapasite ve rota süresi kısıtlarını birlikte kullanan
Peker & Türsel Eliiyi (2023) uygulamasıyla uyumludur.

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

Enlem ve boylam tüm aktif çalışanlar için doldurulmalıdır. Fabrika koordinatları gerçek servis
kapısı konumuyla değiştirilmelidir.

### Mevcut / aday durak dosyası (önerilir)

Mevcut durakları ve saha ekibinin değerlendireceği aday noktaları ayrıca yükleyebilirsiniz.
Dosyada şu sütunlar bulunmalıdır:

- `Durak_Adi` (isteğe bağlı)
- `Enlem`
- `Boylam`

`Saha_Onayi` sütununda `Uygun Değil` veya `Reddedildi` olan satırlar kullanılmaz;
`Bekliyor` olan satırlar planlama adayı olarak kalır ve kesinleştirilmeden önce sahada
kontrol edilmelidir. Durak dosyası kullanılmazsa sistem geometrik ortak noktalar üretir. Bu noktalar
matematiksel adaydır; servise alınmadan önce güvenli bekleme alanı, yol tarafı, yaya
geçidi ve kaldırım açısından sahada onaylanmalıdır.

## Yeni çalışan ve adres değişikliği

İlk plan için **Tam optimizasyon** çalıştırılır ve `servis_rota_sonuclari.xlsx` dosyası
indirilir. Daha sonra çalışan Excel'i güncellendiğinde **Mevcut planı koruyarak güncelle**
seçilir; önceki sonuç Excel'i de uygulamaya yüklenir.

Artımlı mod şu sırayla çalışır:

1. Hâlâ aktif olan çalışanların önceki durak ve rota eşleşmesini korur.
2. Yeni veya adresi değişen çalışanı 500 m sınırındaki mevcut durağa eklemeyi dener.
3. Uygun mevcut durak yoksa yüklenen durak adaylarını değerlendirir.
4. Seçilen politika izin veriyorsa yalnızca gerekli bölgede otomatik aday durak önerir.
5. Yeni durağı mevcut durak sırasını bozmadan en düşük ek süreli yere ekler.
6. Kapasite veya süre yetmezse otomatik modda yeni araç açar; sabit 3 araç modunda
   kullanıcıya tam optimizasyon veya kapasite değişikliği gerektiğini bildirir.

İşten ayrılan çalışanı silmek yerine `Aktif_mi=Hayır` veya
`Servis_Kullaniyor_mu=Hayır` yapmak kayıt geçmişinin korunmasını sağlar. Artımlı
eşleştirme için çalışan sicil/ID değerleri dolu ve benzersiz olmalıdır.

## Önemli not

Yürüyüş mesafesi, kuş uçuşu mesafeye şehir içi sapmaları temsil eden %20 güvenlik payı
eklenerek tahmin edilir. Üretim kullanımında çalışan-durak yürüyüş mesafelerinin gerçek
yaya yolu ağıyla doğrulanması gerekir. Rota başlamadan önce yol yasakları, durak güvenliği,
kaldırım/yaya geçidi, vardiya saati ve trafik koşulları operasyon ekibi tarafından kontrol edilmelidir.

## Literatür

- Schittekat, P. vd. (2013), *A metaheuristic for the school bus routing problem with bus stop selection*, European Journal of Operational Research, 229(2), 518–528. DOI: 10.1016/j.ejor.2013.02.025
- Peker, A. & Türsel Eliiyi, D. (2023), *A Case Study for the Employee Shuttle Routing Problem*, European Journal of Science and Technology. DOI: 10.31590/ejosat.1173057
- Gendreau, M., Laporte, G. & Semet, F. (1997), *The Covering Tour Problem*, Operations Research, 45(4), 568–576.
