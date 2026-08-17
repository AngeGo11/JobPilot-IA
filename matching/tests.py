"""
Tests de non-régression pour matching/services/francetravail.py :
- get_access_token met en cache le token OAuth2 (clé 'francetravail_access_token')
  via django.core.cache.cache pour éviter un appel réseau à chaque recherche.
- Les appels requests.post/requests.get utilisent un timeout=30.
"""
from unittest.mock import MagicMock, patch

from django.core.cache import cache
from django.test import TestCase

from matching.services.francetravail import TOKEN_CACHE_KEY, FranceTravail


class FranceTravailTokenCacheTests(TestCase):
    def setUp(self):
        cache.clear()

    def tearDown(self):
        cache.clear()

    def _mock_token_response(self, access_token="fake-access-token", expires_in=1500):
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.json.return_value = {
            "access_token": access_token,
            "expires_in": expires_in,
        }
        return mock_response

    @patch("matching.services.francetravail.requests.post")
    def test_second_call_uses_cache_and_skips_http_call(self, mock_post):
        mock_post.return_value = self._mock_token_response()
        client = FranceTravail()

        token1 = client.get_access_token("client-id", "client-secret")
        self.assertEqual(token1, "fake-access-token")
        self.assertEqual(mock_post.call_count, 1)

        # Deuxième appel : doit être servi depuis le cache Django, sans nouvel appel HTTP.
        token2 = client.get_access_token("client-id", "client-secret")
        self.assertEqual(token2, "fake-access-token")
        self.assertEqual(mock_post.call_count, 1)  # toujours 1, pas de nouvel appel réseau

    @patch("matching.services.francetravail.requests.post")
    def test_token_is_stored_under_expected_cache_key(self, mock_post):
        mock_post.return_value = self._mock_token_response()
        client = FranceTravail()
        client.get_access_token("client-id", "client-secret")

        self.assertEqual(cache.get(TOKEN_CACHE_KEY), "fake-access-token")

    @patch("matching.services.francetravail.requests.post")
    def test_post_call_uses_timeout_30(self, mock_post):
        mock_post.return_value = self._mock_token_response()
        client = FranceTravail()
        client.get_access_token("client-id", "client-secret")

        _, kwargs = mock_post.call_args
        self.assertEqual(kwargs.get("timeout"), 30)

    @patch("matching.services.francetravail.requests.get")
    @patch("matching.services.francetravail.requests.post")
    def test_search_jobs_get_call_uses_timeout_30(self, mock_post, mock_get):
        mock_post.return_value = self._mock_token_response()
        mock_get_response = MagicMock()
        mock_get_response.status_code = 200
        mock_get_response.json.return_value = {"resultats": []}
        mock_get.return_value = mock_get_response

        client = FranceTravail()
        client.search_jobs(["python"])

        _, kwargs = mock_get.call_args
        self.assertEqual(kwargs.get("timeout"), 30)
