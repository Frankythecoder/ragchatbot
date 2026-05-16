#!/usr/bin/env bash
# Render build step. Installs Python dependencies, collects static files for
# Whitenoise to serve, and applies database migrations.
set -o errexit

pip install --upgrade pip
pip install -r requirements.txt

python manage.py collectstatic --noinput
python manage.py migrate --noinput
