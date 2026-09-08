from app.testing import APIClient, TestCase
from app.urls import reverse


CATEGORIES_URL = reverse('recipe:category-list')
ME_URL = reverse('user:me')
RECIPE_ROOT_URL = '/api/recipe/'
ADMIN_USERS_URL = reverse('user:admin:users-list')


class WireContractTests(TestCase):
    """Framework surface the API answers with, independent of any view."""

    def setUp(self):
        self.client = APIClient()

    def test_allow_header_lists_the_supported_methods(self):
        res = self.client.get(CATEGORIES_URL)

        self.assertEqual(res.status_code, 200)
        self.assertIn('GET', res['Allow'])
        self.assertIn('OPTIONS', res['Allow'])

    def test_json_content_type_carries_no_charset(self):
        res = self.client.get(CATEGORIES_URL)

        self.assertEqual(res['Content-Type'], 'application/json')

    def test_anonymous_unsupported_method_is_unauthorized(self):
        res = self.client.post(ME_URL, {})

        self.assertEqual(res.status_code, 401)

    def test_security_headers_are_present_on_a_view_response(self):
        res = self.client.get(CATEGORIES_URL)

        self.assertEqual(res['X-Frame-Options'], 'DENY')
        self.assertEqual(res['X-Content-Type-Options'], 'nosniff')
        self.assertEqual(res['Referrer-Policy'], 'same-origin')
        self.assertEqual(res['Cross-Origin-Opener-Policy'], 'same-origin')

    def test_locale_headers_announce_turkish(self):
        res = self.client.get(CATEGORIES_URL)

        self.assertEqual(res['Content-Language'], 'tr')
        self.assertEqual(res['Vary'], 'Accept, Accept-Language')

    def test_missing_trailing_slash_redirects_before_the_locale_layer(self):
        res = self.client.get(CATEGORIES_URL.rstrip('/'))

        self.assertEqual(res.status_code, 301)
        self.assertEqual(res['Location'], CATEGORIES_URL)
        self.assertEqual(res['X-Content-Type-Options'], 'nosniff')
        self.assertNotIn('X-Frame-Options', res.headers)
        self.assertNotIn('Content-Language', res.headers)

    def test_double_slash_is_not_found(self):
        res = self.client.get(CATEGORIES_URL + '/')

        self.assertEqual(res.status_code, 404)

    def test_no_cross_origin_headers_are_ever_emitted(self):
        res = self.client.options(
            CATEGORIES_URL,
            headers={
                'Origin': 'https://example.com',
                'Access-Control-Request-Method': 'GET',
            },
        )

        emitted = [name for name in res.headers
                   if name.lower().startswith('access-control-')]
        self.assertEqual(emitted, [])

    def test_json_body_is_compact_and_unterminated(self):
        body = self.client.get(RECIPE_ROOT_URL).content

        self.assertNotIn(b', ', body)
        self.assertNotIn(b': ', body)
        self.assertFalse(body.endswith(b'\n'))

    def test_head_on_a_public_list_answers_like_get(self):
        res = self.client.head(CATEGORIES_URL)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], 'application/json')

    def test_admin_router_rejects_anonymous_with_forbidden(self):
        res = self.client.get(ADMIN_USERS_URL)

        self.assertEqual(res.status_code, 403)
        self.assertNotIn('WWW-Authenticate', res.headers)

    def test_token_first_endpoint_names_its_scheme(self):
        res = self.client.get(ME_URL)

        self.assertEqual(res.status_code, 401)
        self.assertEqual(res['WWW-Authenticate'], 'Token')
        self.assertEqual(res.data, {'detail': 'Giriş bilgileri verilmedi.'})
