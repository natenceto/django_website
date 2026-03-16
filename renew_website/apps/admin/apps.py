from django.apps import AppConfig


class AdminConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'renew_website.apps.admin'
    label = 'renew_admin'
    verbose_name = 'Administration'
    
    def ready(self):
        """Import admin module when app is ready."""
        from . import admin
