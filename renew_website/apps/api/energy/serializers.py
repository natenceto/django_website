"""
Energy management API serializers.
"""
from rest_framework import serializers
from .models import Inverter, InverterReading, WorkMode


class WorkModeSerializer(serializers.ModelSerializer):
    """Serializer for WorkMode model."""
    
    class Meta:
        model = WorkMode
        fields = [
            'mode', 'control_mode', 'is_active', 
            'algorithm_selected_mode', 'last_updated'
        ]


class InverterSerializer(serializers.ModelSerializer):
    """Serializer for Inverter model."""
    
    class Meta:
        model = Inverter
        fields = [
            'id', 'device_sn', 'device_id', 'device_type', 
            'product_id', 'station_id', 'is_active', 'created_at'
        ]


class InverterReadingSerializer(serializers.ModelSerializer):
    """Serializer for InverterReading model."""
    inverter = InverterSerializer(read_only=True)
    
    class Meta:
        model = InverterReading
        fields = [
            'id', 'inverter', 'generation_power', 'battery_soc',
            'grid_power', 'connect_status', 'timestamp', 'collection_time'
        ]


class InverterReadingSnapshotSerializer(serializers.Serializer):
    device_sn = serializers.CharField()
    generation_power = serializers.FloatField(allow_null=True)
    battery_soc = serializers.FloatField(allow_null=True)
    connect_status = serializers.IntegerField()
    timestamp = serializers.DateTimeField()


class CurrentGenerationSummarySerializer(serializers.Serializer):
    total_generation_watts = serializers.FloatField()
    average_battery_soc = serializers.FloatField()
    active_inverters = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    readings = InverterReadingSnapshotSerializer(many=True)




class DashboardDataSerializer(serializers.Serializer):
    """Serializer for dashboard data response."""
    total_generation_watts = serializers.FloatField()
    average_battery_soc = serializers.FloatField()
    active_inverters = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    readings = InverterReadingSnapshotSerializer(many=True)
    
    # Daily stats
    total_energy_kwh = serializers.FloatField()
    peak_generation_watts = serializers.FloatField()


class ChargingRecommendationRequestSerializer(serializers.Serializer):
    """Serializer for charging recommendation request."""
    vehicle_id = serializers.CharField(max_length=100)
    target_soc = serializers.IntegerField(min_value=0, max_value=100)
    current_soc = serializers.IntegerField(min_value=0, max_value=100)
    max_power = serializers.IntegerField(min_value=0)


class ChargingRecommendationResponseSerializer(serializers.Serializer):
    """Serializer for charging recommendation response."""
    should_charge = serializers.BooleanField()
    available_solar_watts = serializers.FloatField()
    charging_power_watts = serializers.FloatField()
    estimated_time_hours = serializers.FloatField()
    battery_soc = serializers.FloatField()


class InverterHistoryPointSerializer(serializers.Serializer):
    timestamp = serializers.DateTimeField()
    generation_power = serializers.FloatField(allow_null=True)
    battery_soc = serializers.FloatField(allow_null=True)
    grid_power = serializers.FloatField(allow_null=True)
    connect_status = serializers.IntegerField()


class InverterHistoryResponseSerializer(serializers.Serializer):
    device_sn = serializers.CharField()
    period_hours = serializers.IntegerField()
    readings = InverterHistoryPointSerializer(many=True)


class StrategyScenarioSerializer(serializers.Serializer):
    strategy = serializers.CharField()
    power_allowed = serializers.FloatField()
    advice = serializers.CharField()
    allocation_plan = serializers.JSONField()


class StrategyCurrentSnapshotSerializer(serializers.Serializer):
    battery_soc = serializers.FloatField(allow_null=True)
    pv_power_kw = serializers.FloatField(allow_null=True)
    load_power_kw = serializers.FloatField(allow_null=True)
    weather_condition = serializers.CharField(allow_blank=True, allow_null=True)
    cloud_cover_percent = serializers.FloatField(allow_null=True)
    weather_solar_score = serializers.FloatField(allow_null=True)
    weather_risk_score = serializers.FloatField(allow_null=True)
    is_night_tariff = serializers.BooleanField()
    active_ev_sessions = serializers.IntegerField()
    total_ev_demand_kw = serializers.FloatField()


class RecommendedPlanSerializer(serializers.Serializer):
    strategy = serializers.CharField()
    strategy_label = serializers.CharField()
    active_ev_sessions = serializers.IntegerField()
    requested_ev_demand_kw = serializers.FloatField()
    ev_power_limit_kw = serializers.FloatField()
    allocation_plan = serializers.JSONField()
    current_snapshot = StrategyCurrentSnapshotSerializer()


class ChargingRecommendationSummarySerializer(serializers.Serializer):
    context = serializers.CharField()
    scenario_1_ev = StrategyScenarioSerializer()
    scenario_2_ev = StrategyScenarioSerializer()
    recommended_plan = RecommendedPlanSerializer()


class MessageTimestampSerializer(serializers.Serializer):
    message = serializers.CharField()
    timestamp = serializers.DateTimeField()


class DashboardCurrentSerializer(serializers.Serializer):
    total_generation_watts = serializers.FloatField()
    average_battery_soc = serializers.FloatField()
    active_inverters = serializers.IntegerField()
    timestamp = serializers.DateTimeField()
    readings = InverterReadingSnapshotSerializer(many=True)
    grid_power_watts = serializers.FloatField(required=False)
    load_power_watts = serializers.FloatField(required=False)
    battery_power_watts = serializers.FloatField(required=False)
    ev_power_watts = serializers.FloatField(required=False)
    active_ev_sessions = serializers.IntegerField(required=False)


class ProductionSummarySerializer(serializers.Serializer):
    current_power_watts = serializers.FloatField()
    installed_capacity_kwp = serializers.FloatField()
    daily_energy_kwh = serializers.FloatField()
    monthly_energy_kwh = serializers.FloatField()
    total_energy_kwh = serializers.FloatField()
    source = serializers.CharField()


class DailyStatsSerializer(serializers.Serializer):
    total_energy_kwh = serializers.FloatField()
    peak_generation_watts = serializers.FloatField()
    average_battery_soc = serializers.FloatField()


class DashboardRecentReadingSerializer(serializers.Serializer):
    device_sn = serializers.CharField()
    generation_power = serializers.FloatField(allow_null=True)
    battery_soc = serializers.FloatField(allow_null=True)
    timestamp = serializers.DateTimeField()


class EnergyDashboardSerializer(serializers.Serializer):
    connection_source = serializers.CharField()
    current = DashboardCurrentSerializer()
    production_summary = ProductionSummarySerializer()
    daily_stats = DailyStatsSerializer()
    recent_readings = DashboardRecentReadingSerializer(many=True)


class WorkModeSyncSerializer(serializers.Serializer):
    current_mode = serializers.CharField(required=False, allow_null=True)
    device_sn = serializers.CharField(required=False, allow_null=True)
    last_sync = serializers.DateTimeField(required=False)
    authoritative = serializers.CharField(required=False)
    source = serializers.CharField(required=False, allow_null=True)
    note = serializers.CharField(required=False, allow_null=True)
    synced = serializers.BooleanField(required=False)
    timestamp = serializers.DateTimeField(required=False)


class WorkModeConfigResponseSerializer(WorkModeSerializer):
    deye_sync = WorkModeSyncSerializer()


class ChartDataSetsSerializer(serializers.Serializer):
    pv_generation = serializers.ListField(child=serializers.FloatField())
    battery_soc = serializers.ListField(child=serializers.FloatField())
    building_load = serializers.ListField(child=serializers.FloatField())
    grid_power = serializers.ListField(child=serializers.FloatField())


class ChartDataResponseSerializer(serializers.Serializer):
    labels = serializers.ListField(child=serializers.CharField())
    datasets = ChartDataSetsSerializer()


class GenericStatusResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()


class EMSApplyResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    stations_updated = serializers.IntegerField(required=False)
    total_connectors_updated = serializers.IntegerField(required=False)
    applied_ev_limit_kw = serializers.FloatField(required=False)
    updated_connectors = serializers.ListField(child=serializers.CharField(), required=False)
    skipped_connectors = serializers.ListField(child=serializers.CharField(), required=False)
    errors = serializers.ListField(child=serializers.CharField(), required=False)


class RecommendationSystemStateSerializer(serializers.Serializer):
    battery_soc = serializers.FloatField()
    pv_production_kw = serializers.FloatField()
    building_load_kw = serializers.FloatField()


class RecommendationDetailSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    mode = serializers.CharField()
    ev_power_limit_kw = serializers.FloatField()
    power_per_station_kw = serializers.FloatField()
    active_ev_sessions = serializers.IntegerField()
    system_state = RecommendationSystemStateSerializer()
    expires_in_seconds = serializers.IntegerField()
    expires_at = serializers.DateTimeField()
    created_at = serializers.DateTimeField()
    algorithm_data = serializers.JSONField()


class EnergyRecommendationsResponseSerializer(serializers.Serializer):
    has_recommendation = serializers.BooleanField()
    message = serializers.CharField(required=False)
    recommendation = RecommendationDetailSerializer(required=False)


class RecommendationActionResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    applied_at = serializers.DateTimeField(required=False)


class RecommendationHistoryItemSerializer(serializers.Serializer):
    id = serializers.IntegerField()
    mode = serializers.CharField()
    ev_power_limit_kw = serializers.FloatField()
    power_per_station_kw = serializers.FloatField()
    status = serializers.CharField()
    active_ev_sessions = serializers.IntegerField()
    battery_soc = serializers.FloatField()
    pv_production_kw = serializers.FloatField()
    created_at = serializers.DateTimeField()
    applied_at = serializers.DateTimeField(allow_null=True)
    expires_at = serializers.DateTimeField()


class RecommendationHistoryResponseSerializer(serializers.Serializer):
    history = RecommendationHistoryItemSerializer(many=True)
    total_count = serializers.IntegerField()


class CollectEnergyDataResponseSerializer(serializers.Serializer):
    success = serializers.BooleanField()
    message = serializers.CharField()
    data = CurrentGenerationSummarySerializer()
    timestamp = serializers.DateTimeField()


class RunAlgorithmResponseSerializer(serializers.Serializer):
    message = serializers.CharField()
    selected_mode = serializers.CharField()
    selected_mode_display = serializers.CharField()
    allocation_plan = serializers.JSONField()
    deye_sync = WorkModeSyncSerializer()


class ErrorResponseSerializer(serializers.Serializer):
    error = serializers.CharField()
