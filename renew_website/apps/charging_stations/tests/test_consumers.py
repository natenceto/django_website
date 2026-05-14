from django.test import SimpleTestCase
from types import SimpleNamespace
from datetime import datetime, timezone as dt_timezone
from asgiref.sync import async_to_sync

from renew_website.apps.charging_stations.consumers import ChargePoint


class _DummyWebSocket:
    async def send(self, message: str):
        return None

    async def recv(self):
        return ""


class ChargePointPendingRemoteStartTests(SimpleTestCase):
    def test_pending_remote_start_falls_back_to_single_connector_match(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)
        pending_key = (1, "000000010160897")
        charge_point.pending_requested_power[pending_key] = 11
        charge_point.pending_session_context[pending_key] = {
            "runtime_type": "simulated",
            "session_source": "simulated",
        }

        matched_key, requested_power, session_context = charge_point._resolve_pending_remote_start(
            1,
            "000000010159376",
        )

        self.assertEqual(matched_key, pending_key)
        self.assertEqual(requested_power, 11)
        self.assertEqual(session_context["runtime_type"], "simulated")

    def test_pending_remote_start_does_not_guess_when_multiple_candidates_exist(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)
        charge_point.pending_requested_power[(1, "tag-a")] = 11
        charge_point.pending_requested_power[(1, "tag-b")] = 22

        matched_key, requested_power, session_context = charge_point._resolve_pending_remote_start(
            1,
            "different-tag",
        )

        self.assertIsNone(matched_key)
        self.assertIsNone(requested_power)
        self.assertEqual(session_context, {})

    def test_remote_start_exact_match_returns_requested_power(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)
        pending_key = (1, "000000010160897")
        charge_point.pending_requested_power[pending_key] = 22

        matched_key, requested_power, session_context = charge_point._resolve_pending_remote_start(
            1,
            "000000010160897",
        )

        self.assertEqual(matched_key, pending_key)
        self.assertEqual(requested_power, 22)
        self.assertEqual(session_context, {})

    def test_desired_station_configuration_uses_production_defaults(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)

        config = charge_point._desired_station_configuration()

        self.assertEqual(config["HeartbeatInterval"], "60")
        self.assertEqual(config["MeterValueSampleInterval"], "30")
        self.assertEqual(config["ClockAlignedDataInterval"], "0")
        self.assertIn("Energy.Active.Import.Register", config["MeterValuesSampledData"])

    def test_configuration_map_from_response_extracts_values_and_readonly(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)
        response = SimpleNamespace(
            configuration_key=[
                SimpleNamespace(key="NumberOfConnectors", value="2", readonly=True),
                SimpleNamespace(key="MeterValueSampleInterval", value="30", readonly=False),
            ]
        )

        config_map = charge_point._configuration_map_from_response(response)

        self.assertEqual(config_map["NumberOfConnectors"]["value"], "2")
        self.assertTrue(config_map["NumberOfConnectors"]["readonly"])
        self.assertEqual(config_map["MeterValueSampleInterval"]["value"], "30")
        self.assertFalse(config_map["MeterValueSampleInterval"]["readonly"])

    def test_extract_vehicle_attributes_maps_richer_vehicle_profile(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)

        attrs = charge_point._extract_vehicle_attributes(
            {
                "vehicle": {
                    "vin": "VIN1234567890",
                    "registrationNumber": "CB0001AA",
                    "manufacturer": "BMW",
                    "model": "i4",
                    "modelYear": 2025,
                    "trim": "eDrive40",
                    "color": "Black",
                    "soc": 63,
                },
                "battery": {
                    "capacityKwh": "83.9",
                    "chemistry": "NMC",
                },
                "estimatedRangeKm": 320,
            }
        )

        self.assertEqual(attrs["vin"], "VIN1234567890")
        self.assertEqual(attrs["registration_number"], "CB0001AA")
        self.assertEqual(attrs["manufacturer"], "BMW")
        self.assertEqual(attrs["model_name"], "i4")
        self.assertEqual(attrs["model_year"], 2025)
        self.assertEqual(attrs["trim"], "eDrive40")
        self.assertEqual(attrs["color"], "Black")
        self.assertEqual(attrs["last_known_soc_percent"], 63.0)
        self.assertEqual(str(attrs["battery_capacity_kwh"]), "83.9")
        self.assertEqual(attrs["metadata"]["battery_chemistry"], "NMC")
        self.assertEqual(attrs["metadata"]["estimated_range_km"], 320)

    def test_parse_vendor_soc_data_accepts_telemetry_snapshot_soc(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)

        soc_data = charge_point.parse_vendor_soc_data(
            {
                "vendor": "ABB",
                "soc": 35,
                "powerKw": 22,
                "sessionActive": True,
                "timestamp": "2026-05-14T15:50:22.426Z",
            },
            "ABB",
        )

        self.assertIsNotNone(soc_data)
        self.assertEqual(soc_data["percentage"], 35)
        self.assertEqual(soc_data["source"], "vendor:abb")
        self.assertEqual(soc_data["timestamp"], datetime(2026, 5, 14, 15, 50, 22, 426000, tzinfo=dt_timezone.utc))

    def test_firmware_status_notification_returns_empty_ack_payload(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)

        response = async_to_sync(charge_point.on_firmware_status_notification)(status="Downloaded")

        self.assertEqual(getattr(response, "__dict__", {}), {})

    def test_call_clear_cache_uses_clear_cache_payload(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)

        async def fake_call_with_logging(action_name, request_payload):
            return action_name, request_payload

        charge_point._call_with_logging = fake_call_with_logging

        action_name, request_payload = async_to_sync(charge_point.call_clear_cache)()

        self.assertEqual(action_name, "ClearCache")
        self.assertEqual(request_payload.__class__.__name__, "ClearCachePayload")

    def test_call_trigger_message_builds_trigger_message_payload(self):
        charge_point = ChargePoint(1, _DummyWebSocket(), consumer=None)

        async def fake_call_with_logging(action_name, request_payload):
            return action_name, request_payload

        charge_point._call_with_logging = fake_call_with_logging

        action_name, request_payload = async_to_sync(charge_point.call_trigger_message)("Heartbeat", connector_id=1)

        self.assertEqual(action_name, "TriggerMessage")
        self.assertEqual(request_payload.__class__.__name__, "TriggerMessagePayload")
        self.assertEqual(getattr(request_payload, "requested_message", None), "Heartbeat")
        self.assertEqual(getattr(request_payload, "connector_id", None), 1)