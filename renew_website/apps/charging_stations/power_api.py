"""
Power Management API Endpoints.

REST API endpoints for controlling charging power and monitoring energy consumption.
"""

import logging
from django.http import JsonResponse
from django.views.decorators.http import require_http_methods
from django.views.decorators.csrf import csrf_exempt
from django.contrib.auth.decorators import login_required
from django.utils.decorators import method_decorator
from django.views import View
from .models import Station, Connector, Transaction
from .power_management import PowerManager, EnergyManager, SafetyMonitor
from .authorization import AuthorizationManager

logger = logging.getLogger('charging_stations')


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class PowerControlView(View):
    """API endpoint for controlling charging power."""
    
    async def post(self, request, station_id, connector_id):
        """Set charging power for a connector."""
        try:
            import json
            data = json.loads(request.body)
            power_kw = float(data.get('power_kw', 0))
            
            # Validate power limits
            if power_kw < 0 or power_kw > 350:  # Max 350kW for ultra-fast chargers
                return JsonResponse({
                    'success': False,
                    'error': 'Power out of range (0-350 kW)'
                }, status=400)
            
            # Check permissions
            if not request.user.has_perm('charging_stations.control_power'):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Set power
            success = await PowerManager.set_charging_power(station_id, connector_id, power_kw)
            
            if success:
                return JsonResponse({
                    'success': True,
                    'message': f'Power set to {power_kw} kW',
                    'station_id': station_id,
                    'connector_id': connector_id,
                    'power_kw': power_kw
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to set power'
                }, status=500)
                
        except ValueError:
            return JsonResponse({
                'success': False,
                'error': 'Invalid power value'
            }, status=400)
        except Exception as e:
            logger.error(f"Error in power control: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)
    
    async def delete(self, request, station_id, connector_id):
        """Stop charging for a connector."""
        try:
            # Check permissions
            if not request.user.has_perm('charging_stations.control_power'):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Stop charging
            success = await PowerManager.stop_charging(station_id, connector_id)
            
            if success:
                return JsonResponse({
                    'success': True,
                    'message': 'Charging stopped',
                    'station_id': station_id,
                    'connector_id': connector_id
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to stop charging'
                }, status=500)
                
        except Exception as e:
            logger.error(f"Error stopping charging: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class SafetyCheckView(View):
    """API endpoint for safety monitoring."""
    
    async def get(self, request, station_id, connector_id=None):
        """Check safety limits for station or connector."""
        try:
            # Check permissions
            if not request.user.has_perm('charging_stations.view_safety'):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Perform safety check
            result = await SafetyMonitor.check_safety_limits(station_id, connector_id)
            
            return JsonResponse({
                'success': True,
                'station_id': station_id,
                'connector_id': connector_id,
                'safe': result['safe'],
                'reason': result.get('reason', ''),
                'timestamp': timezone.now().isoformat()
            })
            
        except Exception as e:
            logger.error(f"Error in safety check: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)
    
    async def post(self, request, station_id, connector_id=None):
        """Execute emergency stop."""
        try:
            import json
            data = json.loads(request.body)
            confirm = data.get('confirm', False)
            
            if not confirm:
                return JsonResponse({
                    'success': False,
                    'error': 'Emergency stop requires confirmation'
                }, status=400)
            
            # Check permissions
            if not request.user.has_perm('charging_stations.emergency_stop'):
                return JsonResponse({
                    'success': False,
                    'error': 'Permission denied'
                }, status=403)
            
            # Execute emergency stop
            success = await SafetyMonitor.emergency_stop(station_id, connector_id)
            
            if success:
                return JsonResponse({
                    'success': True,
                    'message': 'Emergency stop executed',
                    'station_id': station_id,
                    'connector_id': connector_id
                })
            else:
                return JsonResponse({
                    'success': False,
                    'error': 'Failed to execute emergency stop'
                }, status=500)
                
        except Exception as e:
            logger.error(f"Error in emergency stop: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class AuthorizationView(View):
    """API endpoint for RFID authorization."""
    
    def post(self, request):
        """Authorize an RFID tag."""
        try:
            import json
            data = json.loads(request.body)
            
            tag_id = data.get('tag_id')
            station_id = data.get('station_id')
            connector_id = data.get('connector_id')
            
            if not tag_id:
                return JsonResponse({
                    'success': False,
                    'error': 'tag_id is required'
                }, status=400)
            
            # Validate tag format
            valid, reason = AuthorizationManager.validate_tag_format(tag_id)
            if not valid:
                return JsonResponse({
                    'success': False,
                    'error': reason
                }, status=400)
            
            # Authorize tag
            result = AuthorizationManager.authorize_tag(tag_id, station_id, connector_id)
            
            return JsonResponse({
                'success': result['status'] == 'Accepted',
                'authorization': result
            })
            
        except Exception as e:
            logger.error(f"Error in authorization: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)
    
    def get(self, request):
        """Get user transaction history."""
        try:
            tag_id = request.GET.get('tag_id')
            limit = int(request.GET.get('limit', 10))
            
            if not tag_id:
                return JsonResponse({
                    'success': False,
                    'error': 'tag_id is required'
                }, status=400)
            
            # Get transactions
            transactions = AuthorizationManager.get_user_transactions(tag_id, limit)
            
            return JsonResponse({
                'success': True,
                'tag_id': tag_id,
                'transactions': transactions,
                'count': len(transactions)
            })
            
        except Exception as e:
            logger.error(f"Error getting transactions: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)


@method_decorator(csrf_exempt, name='dispatch')
@method_decorator(login_required, name='dispatch')
class EnergyMonitorView(View):
    """API endpoint for energy monitoring and billing."""
    
    def get(self, request, transaction_id):
        """Get energy consumption and cost for a transaction."""
        try:
            transaction = Transaction.objects.get(transaction_id=transaction_id)
            
            # Check if user has permission to view this transaction
            if not request.user.has_perm('charging_stations.view_all_transactions'):
                # Users can only see their own transactions
                if hasattr(request.user, 'profile'):
                    user_tags = request.user.profile.rfid_tags.all()
                    if transaction.id_tag not in [tag.tag for tag in user_tags]:
                        return JsonResponse({
                            'success': False,
                            'error': 'Permission denied'
                        }, status=403)
                else:
                    return JsonResponse({
                        'success': False,
                        'error': 'Permission denied'
                    }, status=403)
            
            # Calculate energy and cost
            if transaction.pricing_plan:
                cost_data = EnergyManager.calculate_energy_cost(transaction, transaction.pricing_plan)
            else:
                # Default pricing if no plan
                cost_data = {
                    'energy_kwh': float(transaction.energy_kwh) if transaction.energy_kwh else 0.0,
                    'energy_cost': 0.0,
                    'connection_fee': 0.0,
                    'total_cost': 0.0,
                    'duration_minutes': 0
                }
            
            return JsonResponse({
                'success': True,
                'transaction_id': str(transaction.transaction_id),
                'station_address': transaction.connector.station.address,
                'connector_id': transaction.connector.connector_id,
                'start_time': transaction.start_timestamp.isoformat() if transaction.start_timestamp else None,
                'stop_time': transaction.stop_timestamp.isoformat() if transaction.stop_timestamp else None,
                'status': 'Active' if not transaction.stop_timestamp else 'Completed',
                'energy': cost_data
            })
            
        except Transaction.DoesNotExist:
            return JsonResponse({
                'success': False,
                'error': 'Transaction not found'
            }, status=404)
        except Exception as e:
            logger.error(f"Error getting energy data: {e}")
            return JsonResponse({
                'success': False,
                'error': 'Internal server error'
            }, status=500)


# URL patterns for power management API
urlpatterns = [
    # Power control
    path('api/v1/power/<int:station_id>/<int:connector_id>/', PowerControlView.as_view(), name='power_control'),
    
    # Safety monitoring
    path('api/v1/safety/<int:station_id>/', SafetyCheckView.as_view(), name='safety_check'),
    path('api/v1/safety/<int:station_id>/<int:connector_id>/', SafetyCheckView.as_view(), name='connector_safety_check'),
    
    # Authorization
    path('api/v1/authorize/', AuthorizationView.as_view(), name='authorize'),
    path('api/v1/transactions/', AuthorizationView.as_view(), name='user_transactions'),
    
    # Energy monitoring
    path('api/v1/energy/<uuid:transaction_id>/', EnergyMonitorView.as_view(), name='energy_monitor'),
]
