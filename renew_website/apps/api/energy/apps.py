from django.apps import AppConfig

class EnergyConfig(AppConfig):
    default_auto_field = 'django.db.models.BigAutoField'
    name = 'renew_website.apps.api.energy'

    def ready(self):
        # Импортираме сигнала, за да е регистриран при стартиране
        import renew_website.apps.api.energy.signals
