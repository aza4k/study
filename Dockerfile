# Asosiy Python versiyasi
FROM python:3.11-slim

# Muhit o'zgaruvchilari
ENV PYTHONUNBUFFERED 1
ENV DJANGO_SETTINGS_MODULE config.settings

# Loyiha katalogini yaratish
WORKDIR /app

# Bog'liqliklarni o'rnatish
COPY requirements.txt /app/
RUN pip install --upgrade pip
RUN pip install -r requirements.txt

# Loyihani nusxalash
COPY . /app/

# Portni ochish (faqat test uchun)
# EXPOSE 8000

# Gunicorn buyrug'i (bu docker-compose.yml da bekor qilinadi, lekin yaxshi amaliyot)
CMD ["gunicorn", "--bind", "0.0.0.0:8000", "config.wsgi:application"]
