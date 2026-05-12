from datetime import timedelta
from decimal import Decimal

from django.test import TestCase
from django.urls import reverse
from django.utils import timezone

from renew_website.apps.charging_stations.models import ChargingSession, Connector, Station, Transaction


class PublicDashboardTests(TestCase):
	def setUp(self):
		self.station = Station.objects.create(
			address="Sofia Tech Park",
			latitude="42.6500",
			longitude="23.3790",
			model="TACW22",
			connector_type="type2",
			power_output=22,
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
		self.assertContains(response, reverse("public:recent_transactions_api"))
		self.assertContains(response, reverse("public:recent_transactions_csv"))
		self.assertContains(response, reverse("public:session_chart_api"))

	def test_recent_transactions_api_returns_rows(self):
		response = self.client.get(reverse("public:recent_transactions_api"), {"timerange": "24h"})

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(len(payload["transactions"]), 1)
		self.assertEqual(payload["transactions"][0]["transaction_id"], "txn-001")
		self.assertEqual(payload["quick_stats"]["successful"], 1)
