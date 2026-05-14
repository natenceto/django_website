from django.contrib.auth import get_user_model
from django.test import TestCase


User = get_user_model()


class ApiAccessPolicyTests(TestCase):
    def setUp(self):
        self.user = User.objects.create_user(
            username='api-user',
            email='api-user@example.com',
            password='strong-pass-123',
        )

    def test_station_list_requires_authentication(self):
        response = self.client.get('/api/v1/stations/')

        self.assertIn(response.status_code, {401, 403})

    def test_connector_list_requires_authentication(self):
        response = self.client.get('/api/v1/connectors/')

        self.assertIn(response.status_code, {401, 403})

    def test_station_list_is_available_for_authenticated_users(self):
        self.client.force_login(self.user)

        response = self.client.get('/api/v1/stations/')

        self.assertEqual(response.status_code, 200)