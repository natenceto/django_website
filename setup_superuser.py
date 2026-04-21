import os
import django
from django.contrib.auth import get_user_model
from django.db.utils import OperationalError

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'renew_website.settings')
django.setup()

User = get_user_model()

try:
    superusers = User.objects.filter(is_superuser=True)
    if superusers.exists():
        print(f"\n--- SUPERUSER EXISTS ---")
        for u in superusers:
            print(f"- Username: {u.username} (Email: {u.email})")
        print("------------------------\n")
    else:
        print("\n--- NO SUPERUSERS FOUND ---")
        print("Creating default superuser: admin / admin123")
        User.objects.create_superuser('admin', 'admin@example.com', 'admin123')
        print("Default superuser created!\n---------------------------\n")
except Exception as e:
    print(f"Error checking superusers: {e}")
