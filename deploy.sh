python manage.py collectstatic --noinput
python manage.py migrate
gunicorn --bind=0.0.0.0 --timeout 600 JobPilot.wsgi:application