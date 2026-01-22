"""
Django management command to collect energy data from inverters.
"""
from django.core.management.base import BaseCommand
from django.utils import timezone
import logging

from renew_website.apps.api.energy.services import InverterDataService

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Collect current energy data from DeyeCloud inverters'

    def add_arguments(self, parser):
        parser.add_argument(
            '--verbose',
            action='store_true',
            help='Enable verbose logging',
        )

    def handle(self, *args, **options):
        """Execute the data collection command."""
        self.stdout.write('Starting energy data collection...')
        
        if options['verbose']:
            logging.getLogger('apps.api.energy').setLevel(logging.DEBUG)
        
        try:
            service = InverterDataService()
            service.collect_current_data()
            
            self.stdout.write(
                self.style.SUCCESS('Energy data collection completed successfully')
            )
            
            # Show summary
            summary = service.get_current_generation_summary()
            self.stdout.write(f"Summary:")
            self.stdout.write(f"   Total Generation: {summary['total_generation_watts']} W")
            self.stdout.write(f"   Battery SOC: {summary['average_battery_soc']}%")
            self.stdout.write(f"   Active Inverters: {summary['active_inverters']}")
            
        except Exception as e:
            self.stdout.write(
                self.style.ERROR(f'Failed to collect energy data: {e}')
            )
            logger.error(f"Energy data collection failed: {e}", exc_info=True)
