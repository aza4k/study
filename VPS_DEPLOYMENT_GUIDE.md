# StuDy AI — VPS Serverga Joylash Bo'yicha To'liq Qo'llanma

Ushbu qo'llanma loyihani yangi xarid qilingan VPS serverga (Ubuntu 20.04 / 22.04 / 24.04 yoki Debian) to'liq sozlab, ishga tushirish uchun tayyorlandi.

Biz loyihaga **2 xil usulda** avtomatlashtirilgan o'rnatish tizimini qo'shdik:
1. **Docker Compose usuli (Tavsiya etiladi)** — bitta buyruq bilan Django, PostgreSQL, Redis, Celery va Nginx konteynerlarda xatosiz ko'tariladi.
2. **Native (Systemd) usuli** — agar VPS resurslari kam bo'lsa (masalan, 1 GB RAM), to'g'ridan-to'g'ri tizim servislariga o'rnatish.

---

## 1-USUL: Docker Compose orqali o'rnatish (Eng tez va qulay)

### 1-qadam: VPS serverga ulanish
Terminal yoki PuTTY orqali serveringizga kiring:
```bash
ssh root@SERVER_IP_MANZILI
```

### 2-qadam: Loyihani serverga yuklab olish (Git orqali)
```bash
cd /var/www || cd ~
git clone https://github.com/aza4k/study.git
cd study
```

### 3-qadam: Muhit o'zgaruvchilari faylini (.env) yaratish
```bash
cp .env.example .env
nano .env
```
Quyidagi qiymatlarni to'ldiring:
- `SECRET_KEY` — tasodifiy uzun kalit.
- `DEBUG=False` — ishlab chiqarishda doim False bo'lishi shart.
- `ALLOWED_HOSTS` — serveringiz IP manzili yoki domeningiz (masalan: `123.45.67.89,study.uz`).
- `CSRF_TRUSTED_ORIGINS` — `http://SERVER_IP,https://SERVER_DOMAIN`.
- `GEMINI_API_KEY` — o'zingizning Google Gemini API kalitingiz.

Saqlash: `Ctrl + O`, `Enter`. Chiqish: `Ctrl + X`.

### 4-qadam: 1-Click avtomatik ishga tushirish
Skriptga ruxsat berib, ishga tushiring:
```bash
chmod +x deploy_vps.sh entrypoint.sh
./deploy_vps.sh
```
Skript quyidagilarni avtomatik bajaradi:
1. Docker va Docker Compose plaginini o'rnatadi.
2. PostgreSQL 16, Redis 7, Celery, Nginx va Django konteynerlarini yig'adi.
3. Ma'lumotlar bazasi migratsiyalarini avtomatik yurgizadi (`migrate`).
4. Statik fayllarni Nginx uchun yig'adi (`collectstatic`).
5. Serverni 80-portda ishga tushiradi!

### 5-qadam: Admin (Superuser) yaratish
```bash
docker compose exec web python manage.py createsuperuser
```

---

## 2-USUL: Native Systemd orqali o'rnatish (Docker'siz)

Agar serveringizda Docker ishlatishni xohlamasangiz:
```bash
cd study
chmod +x setup_systemd.sh
./setup_systemd.sh
```
Ushbu skript PostgreSQL, Redis, Nginx va Systemd servislarini (`study.service`, `study-celery.service`) o'rnatib, sozlab beradi.

---

## 3. Bepul SSL (HTTPS) Sertifikatini Ulash (Let's Encrypt)

Agar siz domenni VPS IP manziliga yo'naltirgan (A-record) bo'lsangiz:

### Docker usulida SSL olish:
Serveringizda `certbot` orqali sertifikat oling:
```bash
sudo apt-get install -y certbot
sudo certbot certonly --webroot -w $(pwd)/nginx/ -d yourdomain.uz -d www.yourdomain.uz
```
Yoki Native usulda bitta buyruq:
```bash
sudo certbot --nginx -d yourdomain.uz -d www.yourdomain.uz
```

---

## 4. Mobil Ilovani (Flutter) VPS Serverga Ulash

Serveringiz ishga tushgach, mobil ilovadagi `ApiConstants.baseUrl` ni o'zgartirasiz:

`mobile_app/lib/core/constants/api_constants.dart` faylida:
```dart
class ApiConstants {
  // Yangi VPS server manzili:
  static const String baseUrl = 'http://SIZNING_VPS_IP/api/v1';
  // Yoki agar domenga SSL ulangan bo'lsa:
  // static const String baseUrl = 'https://study.uz/api/v1';
```

---

## 5. Foydali Server Buyruqlari (Cheat Sheet)

### Konteynerlar holatini tekshirish:
```bash
docker compose ps
```

### Real vaqtda loglarni ko'rish (xatoliklarni kuzatish):
```bash
docker compose logs -f web
docker compose logs -f celery_worker
```

### Kodni yangilash (yangi git pull bo'lganda):
```bash
git pull origin main
docker compose up -d --build
```

### Serverni qayta ishga tushirish:
```bash
docker compose restart
```
