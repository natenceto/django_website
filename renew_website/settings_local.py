from .settings import *
import os

# Local development overrides: use sqlite to avoid requiring Postgres/Redis.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Allow local hosts for the dev server
ALLOWED_HOSTS = ['localhost', '127.0.0.1']
