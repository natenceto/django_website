from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from .models_alerts import AlertSubscription, SystemAlert


User = get_user_model()


class AccountAlertExperienceTests(TestCase):
	def setUp(self):
		self.user = User.objects.create_user(
			username='alerts-user',
			email='alerts@example.com',
			password='strong-pass-123',
			first_name='Alert',
			last_name='Operator',
		)

	def test_account_page_requires_login(self):
		response = self.client.get(reverse('account'))

		self.assertEqual(response.status_code, 302)
		self.assertIn('/accounts/login/', response['Location'])

	def test_account_page_renders_for_authenticated_user(self):
		self.client.force_login(self.user)

		response = self.client.get(reverse('account'))

		self.assertEqual(response.status_code, 200)
		self.assertContains(response, 'Notification Preferences')
		self.assertContains(response, 'Active Alerts Center')

	def test_alert_preferences_endpoint_creates_defaults(self):
		self.client.force_login(self.user)

		response = self.client.get(reverse('accounts:alert_preferences'))

		self.assertEqual(response.status_code, 200)
		payload = response.json()
		self.assertEqual(len(payload['preferences']), len(SystemAlert.CATEGORY_CHOICES))
		self.assertEqual(AlertSubscription.objects.filter(user=self.user).count(), len(SystemAlert.CATEGORY_CHOICES))

	def test_alert_preferences_endpoint_updates_subscriptions(self):
		self.client.force_login(self.user)
		self.client.get(reverse('accounts:alert_preferences'))

		response = self.client.post(
			reverse('accounts:alert_preferences'),
			data={
				'preferences': [
					{
						'category': 'station',
						'severity_min': 'critical',
						'is_web_enabled': False,
						'is_email_enabled': True,
					}
				]
			},
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		subscription = AlertSubscription.objects.get(user=self.user, category='station')
		self.assertEqual(subscription.severity_min, 'critical')
		self.assertFalse(subscription.is_web_enabled)
		self.assertTrue(subscription.is_email_enabled)

	def test_alert_action_endpoint_acknowledges_alert(self):
		self.client.force_login(self.user)
		alert = SystemAlert.objects.create(
			title='Station disconnected',
			message='Station RENEW-01 went offline.',
			severity='warning',
			category='station',
			source='tests',
		)

		response = self.client.post(
			reverse('accounts:alert_action', args=[alert.id]),
			data={'action': 'acknowledge'},
			content_type='application/json',
		)

		self.assertEqual(response.status_code, 200)
		alert.refresh_from_db()
		self.assertTrue(alert.is_acknowledged)
