"""
Sequence Manager for Professional ID Management
Handles proper ID sequencing with data integrity considerations.
"""
from django.db import connection, transaction
from django.core.management.base import BaseCommand
import logging

logger = logging.getLogger(__name__)


class SequenceManager:
    """Manages database sequences for professional ID allocation."""
    
    @staticmethod
    def reset_sequence(model_class, start_value=1):
        """
        Reset sequence for a model to start from specific value.
        
        WARNING: This should only be used in controlled environments
        like data migration or initial setup, not in production.
        
        Args:
            model_class: Django model class
            start_value: Starting value for sequence (default: 1)
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with transaction.atomic():
                # Get table name and sequence name
                table_name = model_class._meta.db_table
                pk_column = model_class._meta.pk.column
                
                # PostgreSQL sequence naming convention
                sequence_name = f"{table_name}_{pk_column}_seq"
                
                with connection.cursor() as cursor:
                    # Reset sequence
                    cursor.execute(
                        f"ALTER SEQUENCE {sequence_name} RESTART WITH %s",
                        [start_value]
                    )
                    
                    # Update existing records if needed
                    if start_value == 1:
                        cursor.execute(
                            f"UPDATE {table_name} SET {pk_column} = DEFAULT"
                        )
                
                logger.info(f"Reset sequence {sequence_name} to start from {start_value}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to reset sequence for {model_class.__name__}: {e}")
            return False
    
    @staticmethod
    def get_sequence_info(model_class):
        """
        Get current sequence information for a model.
        
        Args:
            model_class: Django model class
            
        Returns:
            dict: Sequence information
        """
        try:
            table_name = model_class._meta.db_table
            pk_column = model_class._meta.pk.column
            sequence_name = f"{table_name}_{pk_column}_seq"
            
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT last_value, is_called FROM pg_sequences WHERE sequencename = %s",
                    [sequence_name]
                )
                result = cursor.fetchone()
                
                if result:
                    return {
                        'sequence_name': sequence_name,
                        'last_value': result[0],
                        'is_called': result[1]
                    }
                else:
                    return None
                    
        except Exception as e:
            logger.error(f"Failed to get sequence info for {model_class.__name__}: {e}")
            return None
    
    @staticmethod
    def compact_ids(model_class):
        """
        Compact IDs by renumbering records sequentially.
        This is a DANGEROUS operation and should only be used in development.
        
        Args:
            model_class: Django model class
            
        Returns:
            bool: True if successful, False otherwise
        """
        try:
            with transaction.atomic():
                table_name = model_class._meta.db_table
                pk_column = model_class._meta.pk.column
                
                with connection.cursor() as cursor:
                    # Create temporary mapping
                    cursor.execute(f"""
                        CREATE TEMP SEQUENCE temp_seq START WITH 1;
                        
                        UPDATE {table_name} 
                        SET {pk_column} = nextval('temp_seq')
                        ORDER BY {pk_column};
                        
                        DROP SEQUENCE temp_seq;
                        
                        ALTER SEQUENCE {table_name}_{pk_column}_seq 
                        RESTART WITH (SELECT MAX({pk_column}) + 1 FROM {table_name});
                    """)
                
                logger.warning(f"Compacted IDs for {model_class.__name__}")
                return True
                
        except Exception as e:
            logger.error(f"Failed to compact IDs for {model_class.__name__}: {e}")
            return False


class ProfessionalIDManager:
    """
    Professional ID management with audit trail and business logic.
    """
    
    @staticmethod
    def get_next_available_id(model_class, business_context=None):
        """
        Get next available ID with business context consideration.
        
        Args:
            model_class: Django model class
            business_context: Optional business context for ID allocation
            
        Returns:
            int: Next available ID
        """
        try:
            # Get max current ID
            max_id = model_class.objects.aggregate(
                max_id=models.Max('id')
            )['max_id'] or 0
            
            # Business logic for ID allocation
            if business_context:
                # Add business-specific logic here
                pass
            
            return max_id + 1
            
        except Exception as e:
            logger.error(f"Failed to get next ID for {model_class.__name__}: {e}")
            raise
    
    @staticmethod
    def create_with_managed_id(model_class, **kwargs):
        """
        Create a new instance with professionally managed ID.
        
        Args:
            model_class: Django model class
            **kwargs: Model fields
            
        Returns:
            Model instance
        """
        try:
            # Get next available ID
            next_id = ProfessionalIDManager.get_next_available_id(model_class)
            
            # Create instance with explicit ID
            instance = model_class.objects.create(id=next_id, **kwargs)
            
            logger.info(f"Created {model_class.__name__} with managed ID: {next_id}")
            return instance
            
        except Exception as e:
            logger.error(f"Failed to create {model_class.__name__} with managed ID: {e}")
            raise
