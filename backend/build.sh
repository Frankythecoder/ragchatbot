#!/usr/bin/env bash
# Render build step. Installs Python dependencies, collects static files for
# Whitenoise to serve, applies database migrations, and provisions the
# superuser from env vars (since Render's Shell is paid-only).
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput

# Auto-provision the superuser using DJANGO_SUPERUSER_USERNAME /
# DJANGO_SUPERUSER_PASSWORD / DJANGO_SUPERUSER_EMAIL set in the Render
# dashboard. createsuperuser --noinput errors if the user already exists or
# the env vars aren't set — we swallow that so the build doesn't fail.
python manage.py createsuperuser --noinput 2>&1 \
  || echo "(Superuser already exists or DJANGO_SUPERUSER_* env vars not set — skipping)"
