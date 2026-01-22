from django.apps import AppConfig


class ApiConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'renew_website.apps.api'
    verbose_name = 'REST API'
