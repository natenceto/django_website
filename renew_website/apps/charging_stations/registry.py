from typing import Dict, Set, Any

ACTIVE_STATIONS: Dict[int, Any] = {}

class StationRuntime:
    def __init__(self):
        pass

    def is_online(self, station_id: int) -> bool:
        return station_id in ACTIVE_STATIONS

    def count_online(self) -> int:
        return len(ACTIVE_STATIONS)

    def get_all_online(self) -> Set[int]:
        return set(ACTIVE_STATIONS.keys())

station_runtime = StationRuntime()
