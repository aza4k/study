# Environment Setup Guide

## 📋 Quick Setup

### 1. Create Your `.env` File

Copy the example file and edit it with your values:

```bash
# Copy the example
cp .env.example .env

# Edit with your values
notepad .env  # Windows
# or
nano .env     # Linux/Mac
```

### 2. Required Configuration

**Minimum required settings to get started:**

```env
SECRET_KEY=your-secret-key-here
DEBUG=True
GEMINI_API_KEY=your-gemini-api-key
DB_PASSWORD=Azamat0603
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

### 3. Get Your Gemini API Key

1. Go to [Google AI Studio](https://makersuite.google.com/app/apikey)
2. Click "Create API Key"
3. Copy the key
4. Paste it in your `.env` file: `GEMINI_API_KEY=your-key-here`

---

## 🔐 Security Best Practices

### Generate a New SECRET_KEY

**Never use the default SECRET_KEY in production!**

Generate a new one:

```bash
# Using Python
python -c 'from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())'

# Using PowerShell
docker-compose exec web python -c "from django.core.management.utils import get_random_secret_key; print(get_random_secret_key())"
```

Copy the output and replace `SECRET_KEY` in your `.env` file.

### Production Settings

When deploying to production, update these settings:

```env
DEBUG=False
ALLOWED_HOSTS=yourdomain.com,www.yourdomain.com
SECURE_SSL_REDIRECT=True
SESSION_COOKIE_SECURE=True
CSRF_COOKIE_SECURE=True
```

---

## 📝 Configuration Reference

### Database Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `DB_NAME` | Database name | `study_db` |
| `DB_USER` | Database user | `azmtx` |
| `DB_PASSWORD` | Database password | `Azamat0603` |
| `DB_HOST` | Database host | `db` (Docker) |
| `DB_PORT` | Database port | `5432` |

### Celery Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `CELERY_BROKER_URL` | Redis broker URL | `redis://redis:6379/0` |
| `CELERY_RESULT_BACKEND` | Result backend URL | `redis://redis:6379/0` |

### Django Settings

| Variable | Description | Default |
|----------|-------------|---------|
| `SECRET_KEY` | Django secret key | **MUST CHANGE** |
| `DEBUG` | Debug mode | `True` |
| `ALLOWED_HOSTS` | Allowed hosts (comma-separated) | `localhost,127.0.0.1` |

---

## 🚀 Docker Setup

The `.env` file is automatically loaded by Docker Compose. Just make sure it exists before running:

```bash
docker-compose up -d
```

---

## ⚠️ Important Notes

1. **Never commit `.env` to Git** - It's already in `.gitignore`
2. **Keep `.env.example` updated** - When adding new variables
3. **Use different values** for development and production
4. **Backup your `.env` file** - Store it securely

---

## 🔍 Troubleshooting

### "GEMINI_API_KEY not found"

Make sure your `.env` file has:
```env
GEMINI_API_KEY=your-actual-api-key
```

### "Database connection failed"

Check your database settings:
```env
DB_HOST=db
DB_PORT=5432
DB_NAME=study_db
DB_USER=azmtx
DB_PASSWORD=Azamat0603
```

### "Celery not connecting to Redis"

Verify Redis settings:
```env
CELERY_BROKER_URL=redis://redis:6379/0
CELERY_RESULT_BACKEND=redis://redis:6379/0
```

---

## 📚 Additional Resources

- [Django Settings Documentation](https://docs.djangoproject.com/en/5.2/ref/settings/)
- [Celery Configuration](https://docs.celeryproject.org/en/stable/userguide/configuration.html)
- [Google Gemini API](https://ai.google.dev/)

---

**Last Updated**: December 8, 2025
