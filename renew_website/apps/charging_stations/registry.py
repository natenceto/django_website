import logging
from typing import Dict, Union, Any, Optional, List


logger = logging.getLogger("charging_stations.runtime")


def _normalize_station_key(station_id: Union[int, str]) -> int:
	return int(station_id)


class StationRuntimeService:
	"""Compatibility wrapper for station runtime presence and consumer access."""

	def __init__(self, registry: Optional[Dict[int, Any]] = None):
		self._registry = registry if registry is not None else {}

	def set_online(self, station_id: Union[int, str], consumer: Any) -> None:
		key = _normalize_station_key(station_id)
		self._registry[key] = consumer
		logger.info("Station %s registered in runtime registry", key)

	def set_offline(self, station_id: Union[int, str]) -> None:
		key = _normalize_station_key(station_id)
		self._registry.pop(key, None)
		logger.info("Station %s removed from runtime registry", key)

	def is_online(self, station_id: Union[int, str]) -> bool:
		return _normalize_station_key(station_id) in self._registry

	def get_consumer(self, station_id: Union[int, str]) -> Any:
		return self._registry.get(_normalize_station_key(station_id))

	def get_chargepoint(self, station_id: Union[int, str]) -> Any:
		consumer = self.get_consumer(station_id)
		if consumer and hasattr(consumer, "cp"):
			return consumer.cp
		return None

	def get_all_online(self) -> List[int]:
		return list(self._registry.keys())

	def count_online(self) -> int:
		return len(self._registry)


# Compatibility alias until all callers stop importing the module-level dict directly.
ACTIVE_STATIONS: Dict[int, Any] = {}
station_runtime = StationRuntimeService(ACTIVE_STATIONS)
