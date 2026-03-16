from typing import Dict, Union, Any

# Global registry of active WebSocket consumers
# Key: station_id (int)
# Value: ChargePointConsumer instance
ACTIVE_STATIONS: Dict[int, Any] = {}
