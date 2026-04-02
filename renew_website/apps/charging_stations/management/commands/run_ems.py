import time
from django.core.management.base import BaseCommand
from apps.charging_stations.power_management import EnergyBalancer

class Command(BaseCommand):
    help = 'Стартира Energy Management System за балансиране на мощността'

    def handle(self, *args, **options):
        balancer = EnergyBalancer()
        self.stdout.write(self.style.SUCCESS('EMS стартиран успешно!'))
        
        while True:
            try:
                balancer.run_cycle() # Тук се извиква твоят алгоритъм
                time.sleep(30)       # Изчакване 30 секунди
            except Exception as e:
                self.stdout.write(self.style.ERROR(f"Грешка: {e}"))
                time.sleep(10)       # Кратка пауза при грешка преди рестарт