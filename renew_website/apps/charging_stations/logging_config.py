import logging

def get_ocpp_logger(name: str) -> logging.Logger:
    return logging.getLogger(f"renew.ocpp.{name}")

def get_station_logger(station_id: int) -> logging.Logger:
    return logging.getLogger(f"renew.station.{station_id}")
