"""The three selectors that decide which renderer answers a request.

The baseline offers two renderers on every view and lets a caller choose
between them in three ways: the ``Accept`` header, a ``format`` query
parameter, and a ``.json``/``.api`` suffix on the URL.  The last two are
easy to lose in a port because neither is visible in a route declaration
-- they live in the negotiator and in the router that generates the URL
patterns -- and losing them is not a cosmetic failure: an unknown format
is a ``404`` before authentication even runs, so a missing implementation
turns a rejection into a ``200``.

The ordering asserted here is the baseline's, and all of it is
load-bearing: the suffix outranks the query parameter, the query
parameter outranks ``Accept``, an unknown format answers ``404`` before
``Accept`` is consulted at all, and the whole negotiation happens before
the caller is identified.
"""

from __future__ import annotations

from starlette import status

from app.testing import APIClient, TestCase
from app.urls import reverse

CATEGORIES_URL = reverse('recipe:category-list')
RECIPE_ROOT_URL = '/api/recipe/'
ME_URL = reverse('user:me')

JSON = 'application/json'
HTML = 'text/html; charset=utf-8'
NOT_FOUND = {'detail': 'Bulunamadı.'}


class FormatQueryParameterTests(TestCase):
    """``?format=`` names a renderer directly."""

    def setUp(self):
        self.client = APIClient()
        self.detail_url = CATEGORIES_URL + '5/'

    def test_json_is_served_as_json(self):
        res = self.client.get(self.detail_url, {'format': 'json'})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], JSON)

    def test_api_is_served_as_html(self):
        res = self.client.get(self.detail_url, {'format': 'api'})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], HTML)
        self.assertIn('Cookie', res['Vary'])

    def test_the_override_beats_an_absent_accept_header(self):
        res = self.client.get(
            self.detail_url, {'format': 'api'}, headers={'Accept': ''})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], HTML)

    def test_an_empty_value_is_ignored(self):
        res = self.client.get(self.detail_url + '?format=')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], JSON)

    def test_the_last_of_several_values_wins(self):
        res = self.client.get(self.detail_url + '?format=json&format=api')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], HTML)

    def test_an_unknown_format_is_not_found(self):
        res = self.client.get(self.detail_url, {'format': 'bogus'})

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res['Content-Type'], JSON)
        self.assertEqual(res.data, NOT_FOUND)

    def test_the_match_is_case_sensitive(self):
        res = self.client.get(self.detail_url, {'format': 'JSON'})

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data, NOT_FOUND)

    def test_not_found_outranks_an_unsatisfiable_accept_header(self):
        res = self.client.get(
            self.detail_url, {'format': 'bogus'},
            headers={'Accept': 'text/html'})

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_renderer_the_accept_header_refuses_is_not_acceptable(self):
        res = self.client.get(
            self.detail_url, {'format': 'api'},
            headers={'Accept': JSON})

        self.assertEqual(
            res.status_code, status.HTTP_406_NOT_ACCEPTABLE)
        self.assertEqual(res['Content-Type'], JSON)

    def test_json_is_refused_when_only_html_is_accepted(self):
        res = self.client.get(
            self.detail_url, {'format': 'json'},
            headers={'Accept': 'text/html'})

        self.assertEqual(
            res.status_code, status.HTTP_406_NOT_ACCEPTABLE)

    def test_negotiation_runs_before_the_caller_is_identified(self):
        res = self.client.get(ME_URL, {'format': 'bogus'})

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)

    def test_a_rejection_is_rendered_with_the_chosen_renderer(self):
        res = self.client.get(ME_URL, {'format': 'api'})

        self.assertEqual(res.status_code, status.HTTP_401_UNAUTHORIZED)
        self.assertEqual(res['Content-Type'], HTML)


class FormatSuffixTests(TestCase):
    """``.json`` and ``.api`` name a renderer in the path itself.

    The baseline registers these patterns from its router, so they exist
    under ``/api/recipe/`` and ``/api/user/admin/`` and nowhere else.  The
    lookup value they sit behind excludes the dot, which is what makes an
    unrecognised spelling miss the route entirely rather than resolve and
    then be rejected.
    """

    def setUp(self):
        self.client = APIClient()
        self.detail_url = CATEGORIES_URL + '5/'

    def test_a_collection_carries_the_suffix(self):
        res = self.client.get(CATEGORIES_URL.rstrip('/') + '.json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], JSON)

    def test_a_trailing_slash_after_the_suffix_is_accepted(self):
        res = self.client.get(CATEGORIES_URL.rstrip('/') + '.json/')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], JSON)

    def test_a_record_carries_the_suffix(self):
        suffixed = self.client.get(self.detail_url.rstrip('/') + '.json')
        plain = self.client.get(self.detail_url)

        self.assertEqual(suffixed.status_code, status.HTTP_200_OK)
        self.assertEqual(suffixed.content, plain.content)

    def test_the_api_suffix_selects_the_html_renderer(self):
        res = self.client.get(self.detail_url.rstrip('/') + '.api')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], HTML)

    def test_an_unknown_suffix_is_not_found_as_json(self):
        res = self.client.get(self.detail_url.rstrip('/') + '.bogus')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res['Content-Type'], JSON)
        self.assertEqual(res.data, NOT_FOUND)

    def test_an_uppercase_suffix_misses_the_route(self):
        res = self.client.get(self.detail_url.rstrip('/') + '.JSON')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(res['Content-Type'], JSON)

    def test_a_bare_dot_misses_the_route(self):
        res = self.client.get(self.detail_url.rstrip('/') + '.')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(res['Content-Type'], JSON)

    def test_two_suffixes_miss_the_route(self):
        res = self.client.get(self.detail_url.rstrip('/') + '.json.api')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(res['Content-Type'], JSON)

    def test_the_suffix_outranks_the_query_parameter(self):
        res = self.client.get(
            self.detail_url.rstrip('/') + '.json?format=api')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], JSON)

    def test_the_suffix_is_still_subject_to_the_accept_header(self):
        res = self.client.get(
            self.detail_url.rstrip('/') + '.json',
            headers={'Accept': 'text/html'})

        self.assertEqual(
            res.status_code, status.HTTP_406_NOT_ACCEPTABLE)

    def test_a_prefix_without_suffix_routes_does_not_grow_them(self):
        res = self.client.get(ME_URL.rstrip('/') + '.json')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertNotEqual(res['Content-Type'], JSON)

    def test_the_router_index_answers_under_a_suffix(self):
        res = self.client.get(RECIPE_ROOT_URL + '.json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res['Content-Type'], JSON)

    def test_the_index_hyperlinks_carry_the_suffix_they_were_asked_for(self):
        plain = self.client.get(RECIPE_ROOT_URL)
        suffixed = self.client.get(RECIPE_ROOT_URL + '.json')

        self.assertEqual(
            plain.data['categories'],
            'http://testserver/api/recipe/categories/')
        self.assertEqual(
            suffixed.data['categories'],
            'http://testserver/api/recipe/categories.json')

    def test_an_unknown_suffix_on_the_index_is_not_found(self):
        res = self.client.get(RECIPE_ROOT_URL + '.bogus')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data, NOT_FOUND)
