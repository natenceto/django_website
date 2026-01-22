"""
Django management command for professional sequence management.
"""
from django.core.management.base import BaseCommand, CommandError
from django.apps import apps
from renew_website.utils.sequence_manager import SequenceManager, ProfessionalIDManager
import logging

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = 'Professional sequence management for data integrity'
    
    def add_arguments(self, parser):
        """Add command arguments."""
        subparsers = parser.add_subparsers(dest='action', help='Available actions')
        
        # Reset sequence
        reset_parser = subparsers.add_parser('reset', help='Reset sequence to start value')
        reset_parser.add_argument('model', type=str, help='Model name (app.Model)')
        reset_parser.add_argument('--start', type=int, default=1, help='Start value (default: 1)')
        
        # Get sequence info
        info_parser = subparsers.add_parser('info', help='Get sequence information')
        info_parser.add_argument('model', type=str, help='Model name (app.Model)')
        
        # Compact IDs (DANGEROUS - development only)
        compact_parser = subparsers.add_parser('compact', help='Compact IDs (DEVELOPMENT ONLY)')
        compact_parser.add_argument('model', type=str, help='Model name (app.Model)')
        compact_parser.add_argument('--confirm', action='store_true', help='Confirm dangerous operation')
        
        # List all models with sequences
        subparsers.add_parser('list', help='List all models with sequences')
    
    def handle(self, *args, **options):
        """Handle command execution."""
        action = options['action']
        
        if action == 'reset':
            self.reset_sequence(options['model'], options['start'])
        elif action == 'info':
            self.show_sequence_info(options['model'])
        elif action == 'compact':
            self.compact_ids(options['model'], options['confirm'])
        elif action == 'list':
            self.list_models()
        else:
            self.print_help('manage_sequences', '')
    
    def reset_sequence(self, model_path, start_value):
        """Reset sequence for a model."""
        try:
            model = self.get_model(model_path)
            
            if SequenceManager.reset_sequence(model, start_value):
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully reset sequence for {model_path} to {start_value}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'Failed to reset sequence for {model_path}')
                )
                
        except Exception as e:
            raise CommandError(f'Error resetting sequence: {e}')
    
    def show_sequence_info(self, model_path):
        """Show sequence information."""
        try:
            model = self.get_model(model_path)
            info = SequenceManager.get_sequence_info(model)
            
            if info:
                self.stdout.write(f'Sequence info for {model_path}:')
                self.stdout.write(f'  Sequence: {info["sequence_name"]}')
                self.stdout.write(f'  Last value: {info["last_value"]}')
                self.stdout.write(f'  Called: {info["is_called"]}')
            else:
                self.stdout.write(
                    self.style.WARNING(f'No sequence information found for {model_path}')
                )
                
        except Exception as e:
            raise CommandError(f'Error getting sequence info: {e}')
    
    def compact_ids(self, model_path, confirm):
        """Compact IDs for a model (DANGEROUS)."""
        if not confirm:
            self.stdout.write(
                self.style.ERROR('This is a dangerous operation. Use --confirm to proceed.')
            )
            return
        
        try:
            model = self.get_model(model_path)
            
            self.stdout.write(
                self.style.WARNING('WARNING: This will renumber all records and may break foreign key relationships!')
            )
            
            response = input('Are you absolutely sure you want to continue? (yes/no): ')
            if response.lower() != 'yes':
                self.stdout.write('Operation cancelled.')
                return
            
            if SequenceManager.compact_ids(model):
                self.stdout.write(
                    self.style.SUCCESS(f'Successfully compacted IDs for {model_path}')
                )
            else:
                self.stdout.write(
                    self.style.ERROR(f'Failed to compact IDs for {model_path}')
                )
                
        except Exception as e:
            raise CommandError(f'Error compacting IDs: {e}')
    
    def list_models(self):
        """List all models with sequences."""
        self.stdout.write('Models with auto-incrementing primary keys:')
        
        for model in apps.get_models():
            if hasattr(model._meta.pk, 'auto_created') and model._meta.pk.auto_created:
                app_label = model._meta.app_label
                model_name = model.__name__
                self.stdout.write(f'  {app_label}.{model_name}')
    
    def get_model(self, model_path):
        """Get model from path string."""
        try:
            app_label, model_name = model_path.split('.')
            return apps.get_model(app_label, model_name)
        except (ValueError, LookupError) as e:
            raise CommandError(f'Invalid model path: {model_path}. Use format: app.Model')
