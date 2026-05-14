from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from renew_website.apps.charging_stations.models import ChargingSession, Connector, MeterValue, Station, Transaction


class PublicDashboardTests(TestCase):
	def setUp(self):
		self.station = Station.objects.create(
			address="Sofia Tech Park",
			latitude="42.6500",
			longitude="23.3790",
			model="TACW22",
			connector_type="type2",
			power_output=22,
			runtime_environment="physical",
			last_seen=timezone.now(),
			status="active",
			email="ops@example.com",
		)
		self.connector = Connector.objects.create(
			station=self.station,
			connector_id=1,
			connector_number=1,
			is_primary=True,
			status="charging",
			availability="operative",
			current_power_kw=Decimal("11.50"),
		)
		self.transaction = Transaction.objects.create(
			connector=self.connector,
			transaction_id="txn-001",
			id_tag="EV-123",
			meter_start=1000,
			meter_stop=7000,
			status="completed",
			stopped_at=timezone.now(),
		)
		Transaction.objects.filter(pk=self.transaction.pk).update(
			started_at=timezone.now() - timedelta(hours=1),
			stopped_at=timezone.now(),
		)
		self.transaction.refresh_from_db()
		MeterValue.objects.create(
			transaction=self.transaction,
			value=7000,
			energy_wh=6000,
			power_w=11500,
			data={"reason": "Local", "meter_start": 1000, "meter_stop": 7000},
		)
		ChargingSession.objects.create(
			transaction=self.transaction,
			total_cost=Decimal("12.50"),
			energy_kwh=Decimal("6.000"),
			duration_minutes=60,
		)

	def test_dashboard_index_renders(self):
		response = self.client.get(reverse("public:index"))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, "Dashboard")
		self.assertContains(response, reverse("public:dashboard_live_summary_api"))
		self.assertContains(response, reverse("public:recent_transactions_api"))
		self.assertContains(response, reverse("public:recent_transactions_csv"))
		self.assertContains(response, reverse("public:session_chart_api"))

	def test_recent_transactions_api_returns_rows(self):
		response = self.client.get(reverse("public:recent_transactions_api"), {"timerange": "24h"})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(len(payload["transactions"]), 1)
		self.assertEqual(payload["transactions"][0]["transaction_id"], "txn-001")
		self.assertEqual(payload["transactions"][0]["duration_display"], "01:00:00")
		self.assertEqual(payload["transactions"][0]["session_status"], "Completed")
		self.assertEqual(payload["transactions"][0]["session_authenticity"], "Real Charge")
		self.assertEqual(payload["transactions"][0]["data_quality"], "Good")
		self.assertEqual(payload["transactions"][0]["confidence_score"], "0.98")
		self.assertEqual(payload["quick_stats"]["successful"], 1)
		self.assertEqual(payload["quick_stats"]["simulated"], 0)

	def test_recent_transactions_csv_includes_status_authenticity_and_quality(self):
		response = self.client.get(reverse("public:recent_transactions_csv"), {"timerange": "24h"})

		self.assertEqual(response.status_code, 200)
		content = response.content.decode()
		self.assertIn("Session Status", content)
		self.assertIn("Authenticity", content)
		self.assertIn("Data Quality", content)
		self.assertIn("Confidence Score", content)
		self.assertIn("Telemetry", content)
		self.assertIn("Completed", content)
		self.assertIn("Real Charge", content)
		self.assertIn("Good", content)

	def test_dashboard_live_summary_api_returns_counts(self):
		response = self.client.get(reverse("public:dashboard_live_summary_api"))

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload["active_sessions_count"], 0)
		self.assertEqual(payload["online_stations"], 1)
		self.assertEqual(payload["charger_status_counts"]["charging"], 1)

	def test_simulated_transaction_is_separated_from_successful_count(self):
		simulated_tx = Transaction.objects.create(
			connector=self.connector,
			transaction_id="txn-sim-001",
			id_tag="SIMULATED_DASHBOARD_USER",
			meter_start=1,
			meter_stop=1,
			status="completed",
		)
		Transaction.objects.filter(pk=simulated_tx.pk).update(
			started_at=timezone.now() - timedelta(seconds=30),
			stopped_at=timezone.now(),
		)
		MeterValue.objects.create(
			transaction=simulated_tx,
			value=1,
			data={"reason": "Remote", "meter_start": 1, "meter_stop": 1},
		)

		response = self.client.get(reverse("public:recent_transactions_api"), {"timerange": "24h"})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(payload["quick_stats"]["successful"], 1)
		self.assertEqual(payload["quick_stats"]["simulated"], 1)
		simulated_row = next(tx for tx in payload["transactions"] if tx["transaction_id"] == "txn-sim-001")
		self.assertEqual(simulated_row["session_status"], "Test / Simulated")
		self.assertEqual(simulated_row["session_authenticity"], "Simulated")
		self.assertEqual(simulated_row["data_quality"], "Missing")
		self.assertEqual(simulated_row["confidence_score"], "1.00")

	def test_unverified_station_with_energy_is_not_real_charge(self):
		self.station.runtime_environment = "unknown"
		self.station.save(update_fields=["runtime_environment"])

		response = self.client.get(reverse("public:recent_transactions_api"), {"timerange": "24h"})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		row = next(tx for tx in payload["transactions"] if tx["transaction_id"] == "txn-001")
		self.assertEqual(row["session_status"], "Completed")
		self.assertEqual(row["session_authenticity"], "Unknown")
		self.assertEqual(row["confidence_score"], "0.50")

	def test_zero_energy_real_session_is_unknown_not_simulated(self):
		unknown_tx = Transaction.objects.create(
			connector=self.connector,
			transaction_id="txn-unknown-001",
			id_tag="REAL-UNKNOWN-001",
			meter_start=5000,
			meter_stop=5000,
			status="completed",
			requested_power_kw=11,
		)
		Transaction.objects.filter(pk=unknown_tx.pk).update(
			started_at=timezone.now() - timedelta(minutes=12),
			stopped_at=timezone.now(),
		)
		unknown_tx.refresh_from_db()
		MeterValue.objects.create(
			transaction=unknown_tx,
			value=5000,
			power_w=7200,
			data={"reason": "Remote", "meter_start": 5000, "meter_stop": 5000},
		)

		response = self.client.get(reverse("public:recent_transactions_api"), {"timerange": "24h"})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		unknown_row = next(tx for tx in payload["transactions"] if tx["transaction_id"] == "txn-unknown-001")
		self.assertEqual(unknown_row["session_status"], "Aborted")
		self.assertEqual(unknown_row["session_authenticity"], "Unknown")
		self.assertEqual(unknown_row["data_quality"], "Inconsistent")
		self.assertEqual(unknown_row["confidence_score"], "0.15")
