#!/usr/bin/env python
"""
Fix authenticity badges for transactions 112, 113, 114
by updating their session_context from "simulated" to "platform"
"""
import os
import django

os.environ.setdefault('DJANGO_SETTINGS_MODULE', 'renew_website.settings')
django.setup()

from renew_website.apps.charging_stations.models import Transaction, MeterValue

def fix_transaction_authenticity(tx_ids=[112, 113, 114]):
    """Update session_context for given transactions to mark them as real (platform) sessions."""
    
    for tx_id in tx_ids:
        try:
            tx = Transaction.objects.get(id=tx_id)
            print(f"\n=== Processing Transaction {tx_id} ===")
            print(f"ID Tag: {tx.id_tag}")
            print(f"Status: {tx.status}")
            print(f"Energy: {tx.energy_consumed} kWh")
            print(f"Duration: {tx.duration}")
            
            updated_count = 0
            for meter in tx.meter_values.all():
                data = meter.data or {}
                session_context = data.get("session_context") or {}
                
                # Check if it has "simulated" markers
                old_source = session_context.get("session_source")
                old_runtime_type = session_context.get("runtime_type")
                
                if old_source == "simulated" or old_runtime_type == "simulated":
                    print(f"  Meter {meter.id}: Updating session_context")
                    print(f"    Old session_source: {old_source}")
                    print(f"    Old runtime_type: {old_runtime_type}")
                    
                    # Update to platform/real values
                    session_context["session_source"] = "platform"
                    session_context["runtime_type"] = "real"
                    
                    # Save back to meter_value
                    data["session_context"] = session_context
                    meter.data = data
                    meter.save()
                    
                    print(f"    New session_source: platform")
                    print(f"    New runtime_type: real")
                    updated_count += 1
            
            if updated_count == 0:
                print(f"  No updates needed (already platform or real)")
            else:
                print(f"  Updated {updated_count} meter values")
                
        except Transaction.DoesNotExist:
            print(f"Transaction {tx_id} not found")
        except Exception as e:
            print(f"Error processing transaction {tx_id}: {e}")

if __name__ == "__main__":
    print("Fixing authenticity badges for real charging sessions...")
    print("=" * 60)
    fix_transaction_authenticity()
    print("\n" + "=" * 60)
    print("Done! Sessions should now display as 'Real Charge' instead of 'Test / Simulated'")
