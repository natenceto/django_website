"""
Local development settings override.

This file configures a minimal sqlite-based development environment so you
can run the site locally without PostgreSQL/Redis. It is safe to keep in the
repository; it uses only a local `db.sqlite3` file and localhost settings.

If you prefer not to keep this in the repo, remove the file and create it
locally before running the server as described in the README.
"""
from .settings import *
import os

# Use a local sqlite database for quick development and screenshots.
DATABASES = {
    'default': {
        'ENGINE': 'django.db.backends.sqlite3',
        'NAME': os.path.join(BASE_DIR, 'db.sqlite3'),
    }
}

# Restrict hosts to localhost for this mode
ALLOWED_HOSTS = ['localhost', '127.0.0.1']

# Disable Redis channel layer in local sqlite mode (Channels will use in-memory layer)
USE_REDIS_CHANNEL_LAYER = False
CHANNEL_LAYERS = {
    "default": {
        "BACKEND": "channels.layers.InMemoryChannelLayer",
    }
}
