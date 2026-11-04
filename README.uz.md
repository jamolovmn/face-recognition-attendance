# Yuzni tanish orqali davomat tizimi: PTZ kamera + AI + Nextcloud

> 🇬🇧 English: [README.md](README.md)

**Ochiq kodli xodimlar davomati tizimi.** Oddiy IP yoki Wi-Fi PTZ kameralar ofisni kuzatadi.
AI **kamerani yuzga qarab buradi va zoom qiladi** (ONVIF PTZ), odamni uzoqdan taniydi va
**kim, qachon, qaysi xonaga kelgani**ni maxsus **Nextcloud ilovasi**ga yozadi.

- ✅ **GPU va bulut shart emas**: oddiy CPU serverda ishlaydi, yuzlar tarmog'ingizdan tashqariga chiqmaydi
- ✅ **Tijoriy foydalanishga ruxsat berilgan modellar**: YuNet (MIT) va SFace (Apache-2.0)
- ✅ **Model o'qitish kerak emas**: har bir odamdan 5–10 ta rasm papkaga qo'yiladi, shu yetarli
- ✅ **Kamera o'zi kuzatadi**: tanilmagan yuzni markazga olib zoom qiladi, keyin eshikka qaytadi
- ✅ **Nextcloud ilovasi**: kunlik hisobot (keldi / oxirgi ko'rilgan / kechikdi / kelmadi), barcha hodisalar, begona odamlar rasmi bilan, CSV eksport, eski ma'lumotlarni avtomatik o'chirish
- ✅ **Ishonchli**: bir necha kadrda tasdiqlash, takroriy yozuvlardan himoya, Nextcloud o'chiq bo'lsa hodisalar diskda saqlanib, keyin yuboriladi

## Qanday ishlaydi

1. **Topish.** Kadr (sekundiga 2–3 ta, faqat harakat bo'lganda) **YuNet** modelidan o'tadi.
2. **Tanish.** Har bir yuz tekislanib, 128 o'lchamli **SFace** vektoriga aylantiriladi va rasmlardan qurilgan galereya bilan solishtiriladi.
3. **Tasdiqlash.** Hodisa yozilishi uchun odam **4 soniya ichida 3 marta** tanilishi kerak (begona odam uchun 6 marta).
4. **Kuzatish.** PTZ kamera hali tanilmagan eng katta yuzni markazga oladi va ~120 px bo'lguncha zoom qiladi. 20 soniya yuz bo'lmasa, uy holatiga (eshikka) qaytadi.
5. **Yozish.** Hodisa (ism, xona, kamera, moslik, yuz rasmi) Nextcloud'ga yuboriladi. Bir odam bir xonada 10 daqiqada ko'pi bilan bir marta yoziladi. Kundagi birinchi ko'rinishi "keldi", oxirgisi "ketdi" hisoblanadi.

## 24/7 ishlash, lekin CPU kam sarflanadi

AI har bir kadrda kun bo'yi ishlasa, resurs behuda ketadi. Shuning uchun tizim **kaskad** usulida ishlaydi:
- **Doim:** faqat kichik oqim (640×360) va harakat sensori ishlaydi.
- **Harakat bo'lganda:** katta oqim to'liq ochiladi, yuz qidiriladi.
- **Hamma tanilgan va yozib bo'lingan bo'lsa ("tinch" rejim):** sekundiga 1 marta, kichik o'lchamda tekshiriladi. Tanilgan yuz joyi bo'yicha kuzatiladi va 5 soniyada bir marta qayta tekshiriladi.
- **Ish vaqtidan tashqarida** (`ACTIVE_HOURS`, `ACTIVE_DAYS`): kameralar uziladi, CPU 0%.

3 vCPU serverda, bitta kamera bilan o'lchangan natijalar (bir yadroga nisbatan):

| Holat | CPU |
|---|---|
| Bo'sh xona | **~2–3%** |
| Kimdir kirdi (bir necha soniya) | 60–80% |
| Odamlar kun bo'yi kadrda o'tiradi | **~6–10%** |
| Ish vaqtidan tashqari | **0%** |

## Talablar

| | |
|---|---|
| Server | Docker o'rnatilgan Linux. 2 ta kamera uchun ≈ 1–1.5 CPU yadro |
| Kamera | RTSP (majburiy) + ONVIF PTZ (kuzatish uchun, ixtiyoriy) |
| Tarmoq | Server kameralarning RTSP/ONVIF portlariga ulana olishi kerak (bitta LAN yoki WireGuard VPN) |
| Nextcloud | 30 – 33 |

## Ishga tushirish

```bash
git clone https://github.com/jamolovmn/face-recognition-attendance.git
cd face-recognition-attendance
cp .env.example .env
docker compose build
```

### 1. Kamerani tekshirish (RTSP manzil va PTZ)

```bash
docker compose run --rm attendance python -m attendance.probe 192.168.1.50 --user admin --password parol
docker compose run --rm attendance python -m attendance.probe 192.168.1.50 --user admin --password parol --ptz-test
```

Natijadagi RTSP manzil va ONVIF portni `.env` fayliga yozing.

> Arzon Wi-Fi kameralarning ko'pida ONVIF **o'chirilgan** bo'ladi. Uni kamera ilovasi yoki veb-panelida yoqib, ONVIF parolini o'rnating.

### 2. Xodimlarni qo'shish

```
faces/
  Ali Valiyev/        1.jpg 2.jpg 3.jpg ...
  Dilnoza Karimova/   1.jpg 2.jpg ...
```

```bash
docker compose run --rm attendance python -m attendance.enroll
```

Har bir odamdan 5–10 ta rasm oling: har xil burchak, yorug'lik, ko'zoynakli va ko'zoynaksiz. Papka nomi Nextcloud'da ko'rinadigan ism bo'ladi. Ishlab turgan servis galereyani bir daqiqa ichida o'zi qayta yuklaydi.

### Rasmlarni kameraning o'zi yig'sin

Rasmlarni qo'lda olish o'rniga `.env`da `COLLECT_FACES=true` qiling va `NC_PEOPLE_DIR` hamda `NC_NEW_FACES_DIR`ni yozing:

1. Servis ishlayotganda har bir notanish yuz **aniq, to'g'ri qaragan va yetarlicha katta** bo'lsa, o'xshashligi bo'yicha guruhlanadi. Har bir odamdan 20 tagacha har xil rasm Nextcloud'dagi `Yangi odamlar/person-OYKUN-SSDDSS/` papkasiga tushadi.
2. Papkani oching, yomon rasmlarni o'chiring, so'ng **papka nomini odamning ismiga o'zgartirib, `Xodimlar/` ichiga ko'chiring**. Bir odamga ikkita papka ochilib qolgan bo'lsa, ularni bitta papkaga birlashtiring.
3. Bir daqiqa ichida har bir kompyuter `Xodimlar/` papkasini yuklab oladi, rasmlarni qayta o'qiydi va bu odamni taniy boshlaydi. Asosiy va zaxira kompyuterda xodimlar ro'yxati doim bir xil bo'ladi.

### 3. Nextcloud ilovasini o'rnatish

```bash
cp -r nextcloud-app/faceattendance /nextcloud/yo'li/custom_apps/
chown -R www-data:www-data /nextcloud/yo'li/custom_apps/faceattendance
sudo -u www-data php occ app:enable faceattendance

sudo -u www-data php occ group:add attendance
OC_PASS='uzun-tasodifiy-parol' sudo -E -u www-data php occ user:add --password-from-env --group attendance attendance-bot
sudo -u www-data php occ user:auth-tokens:add attendance-bot   # -> NC_APP_PASSWORD
```

Davomatni faqat **adminlar** va **`attendance`** guruhi a'zolari ko'ra oladi. HR va rahbarlarni shu guruhga qo'shing.

### 4. Ishga tushirish

```bash
docker compose up -d
docker compose logs -f
```

### VPN yoki oq IP yo'qmi? Eski Android telefon yetadi

Ofis provayder modemi orqasida bo'lsa va routerning VPN mijozi kiruvchi ulanishga ruxsat bermasa, ofis ichidagi doim yoqiq istalgan qurilma serverga **o'zi ulanib**, kamera portlarini SSH tunnel orqali uzatib turishi mumkin. Buning uchun [Termux](https://f-droid.org/packages/com.termux/) o'rnatilgan eski Android telefon kifoya. Telefon qayta yonganda tunnel o'zi ishga tushishi uchun [Termux:Boot](https://f-droid.org/packages/com.termux.boot/) ilovasini ham o'rnating. Serverda faqat shu portlarni ocha oladigan alohida foydalanuvchi yaratiladi (batafsil: [README.md](README.md)).

### Ofisdagi Windows kompyuterda ishlatish (Docker'siz), avtomatik zaxira bilan

AI'ni ofisning o'zida ishlatish ko'pincha yaxshiroq. Video ofis tarmog'idan chiqmaydi, tunnel ham, port ochish ham kerak bo'lmaydi. Nextcloud'ga HTTPS orqali faqat kichik hodisalar ketadi.

1. Loyihani `C:\FaceAttendance` papkasiga ko'chiring (yo'lda bo'sh joy bo'lmasin). `.env` fayliga kameralarning ichki IP manzillarini yozing.
2. PowerShell'ni **administrator sifatida** oching:
   ```powershell
   cd C:\FaceAttendance
   powershell -ExecutionPolicy Bypass -File windows\install.ps1
   ```
   Skript Python 3.12 va kutubxonalarni o'rnatadi, modellarni yuklab oladi va kompyuterning uyqu rejimini o'chiradi. So'ng `FaceAttendance` vazifasini qo'shadi: kompyuter yonganda hech kim kirmasa ham servis o'zi ishga tushadi, to'xtab qolsa qayta yonadi. Log fayli: `data\attendance.log`.
3. Kamerani tekshirish va xodimlarni qo'shish Docker'dagi kabi, faqat buyruqlar `.venv\Scripts\python.exe -m attendance.probe ...` va `-m attendance.enroll` bo'ladi.

**2 ta doim yoqiq kompyuter, bittasi asosiy.** Dasturni ikkalasiga o'rnating va `.env`da `FAILOVER=true` qiling. Asosiy kompyuterga `NODE_PRIORITY=1`, zaxirasiga `NODE_PRIORITY=2` yozing. Har ikkalasi Nextcloud'ga ~15 soniyada "tirikman" signalini yuboradi, kameralarga esa faqat aktiv kompyuter ulanadi. Zaxira kompyuter kutib turadi: kamera trafigi yo'q, CPU deyarli 0. Asosiy kompyuter 45 soniya (`LEASE_TTL_SEC`) signal bermasa, ish zaxiraga o'tadi. Asosiy kompyuter qaytib yonsa, ishni yana o'zi oladi. Almashinuv paytida ikkalasi bir lahza birga ishlab qolsa ham, Nextcloud takror yozuvni o'zi tashlab yuboradi (bir odam, bir xona, 2 daqiqa ichida). Ikkala kompyuterda ham `faces/` papkasi bir xil bo'lsin, `enroll`ni har birida ishga tushiring.

## Sozlamalar

Barcha sozlamalar `.env` faylida turadi, har biri [`.env.example`](.env.example) ichida izohlangan.

Ma'lumotlarni saqlash muddati (kun, `0` = cheksiz):
`occ config:app:set faceattendance retention_days --value 90 --type integer`

## Aniqlikni oshirish bo'yicha maslahatlar

- Kadrda yuz **kamida 80–110 px** bo'lishi kerak. Optik zoom yoki eshikka yaqin kamera eng ko'p yordam beradi.
- Kamerani bosh balandligida, kirish eshigiga qaratib o'rnating. Orqadan tushadigan kuchli yorug'likdan (deraza) saqlaning.
- Begona odam boshqa odam deb tanilsa, `MATCH_THRESHOLD`ni oshiring (0.45). Tanish odam "noma'lum" chiqsa, ko'proq rasm qo'shing.
- PTZ kamera bitta odamga zoom qilganda xonaning qolgan qismini ko'rmaydi. Aniq davomat uchun eng yaxshi yechim: eshikda qo'zg'almas kamera va xona uchun PTZ.

## Maxfiylik va qonun

Yuz ma'lumotlari **biometrik shaxsiy ma'lumot** hisoblanadi ("Shaxsga doir ma'lumotlar to'g'risida"gi qonun). Xodimlardan **yozma rozilik** oling, kameralar joyini e'lon qiling, ma'lumotlarni o'z serveringizda saqlang va saqlash muddatini belgilang. `faces/` va `data/` papkalari git'ga kiritilmaydi.

## Litsenziya

[MIT](LICENSE)
