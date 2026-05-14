import os
import django
from django.contrib.auth import get_user_model

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'renew_website.settings')
django.setup()

User = get_user_model()


def _truthy(name: str) -> bool:
    return os.environ.get(name, '').strip().lower() in {'1', 'true', 'yes', 'on'}

try:
    if not _truthy('DJANGO_SUPERUSER_CREATE'):
        print('Skipping automatic superuser creation.')
    else:
        username = os.environ.get('DJANGO_SUPERUSER_USERNAME', '').strip()
        email = os.environ.get('DJANGO_SUPERUSER_EMAIL', '').strip()
        password = os.environ.get('DJANGO_SUPERUSER_PASSWORD', '').strip()

        if not username or not email or not password:
            print('Skipping automatic superuser creation because DJANGO_SUPERUSER_USERNAME, DJANGO_SUPERUSER_EMAIL, and DJANGO_SUPERUSER_PASSWORD must all be set.')
        else:
            superusers = User.objects.filter(is_superuser=True)
            if superusers.exists():
                print('Superuser already exists. Skipping creation.')
            else:
                User.objects.create_superuser(username, email, password)
                print(f'Created superuser {username}.')
except Exception as e:
    print(f"Error checking superusers: {e}")
