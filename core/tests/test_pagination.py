"""The page envelope ``settings.API['DEFAULT_PAGINATION_CLASS']`` names.

Two properties of the envelope are part of the published contract and are
what these tests pin: the key order, because a couple of clients read the
payload positionally, and the two derived links -- ``first_page`` is
``previous`` with its page parameter stripped, ``last_page`` is ``next``
with its page number replaced by the final one.
"""

from __future__ import annotations

from types import SimpleNamespace

from app.testing import TestCase
from core.pagination import CustomPagination, relative

#: The order the envelope's keys have always been emitted in.
ENVELOPE_KEYS = [
    'count',
    'first_page',
    'last_page',
    'next',
    'previous',
    'last_page_number',
    'current_page',
    'results',
]

BASE = 'http://testserver/api/recipe/articles/'


def page(number, next_link=None, previous_link=None, count=100, num_pages=4):
    return SimpleNamespace(
        number=number,
        next_link=next_link,
        previous_link=previous_link,
        paginator=SimpleNamespace(count=count, num_pages=num_pages),
    )


class RelativeTests(TestCase):

    def test_scheme_and_host_are_stripped_and_the_query_is_kept(self):
        self.assertEqual(
            relative(BASE + '?page=3'), '/api/recipe/articles/?page=3')

    def test_a_bare_host_becomes_a_root_path(self):
        self.assertEqual(relative('http://testserver/'), '/')

    def test_a_missing_link_stays_missing(self):
        self.assertIsNone(relative(None))
        self.assertIsNone(relative(''))


class CustomPaginationTests(TestCase):

    def test_the_configured_page_size_and_query_parameter(self):
        self.assertEqual(CustomPagination.page_size, 27)
        self.assertEqual(CustomPagination.page_query_param, 'page')

    def test_a_middle_page_carries_all_four_links(self):
        paginator = CustomPagination(
            page(3, next_link=BASE + '?page=4',
                 previous_link=BASE + '?page=2'))

        envelope = paginator.get_paginated_response(['a', 'b'])

        self.assertEqual(list(envelope), ENVELOPE_KEYS)
        self.assertEqual(envelope['count'], 100)
        self.assertEqual(envelope['first_page'], '/api/recipe/articles/')
        self.assertEqual(
            envelope['last_page'], '/api/recipe/articles/?page=4')
        self.assertEqual(envelope['next'], '/api/recipe/articles/?page=4')
        self.assertEqual(
            envelope['previous'], '/api/recipe/articles/?page=2')
        self.assertEqual(envelope['last_page_number'], 4)
        self.assertEqual(envelope['current_page'], 3)
        self.assertEqual(envelope['results'], ['a', 'b'])

    def test_last_page_replaces_the_page_number_rather_than_the_next_one(
            self):
        paginator = CustomPagination(
            page(2, next_link=BASE + '?page=3',
                 previous_link=BASE, num_pages=9))

        envelope = paginator.get_paginated_response([])

        self.assertEqual(envelope['next'], '/api/recipe/articles/?page=3')
        self.assertEqual(
            envelope['last_page'], '/api/recipe/articles/?page=9')

    def test_first_page_drops_the_page_parameter_of_previous(self):
        paginator = CustomPagination(
            page(4, next_link=None, previous_link=BASE + '?page=3'))

        envelope = paginator.get_paginated_response([])

        self.assertEqual(
            envelope['previous'], '/api/recipe/articles/?page=3')
        self.assertEqual(envelope['first_page'], '/api/recipe/articles/')

    def test_the_opening_page_has_no_backward_links(self):
        paginator = CustomPagination(
            page(1, next_link=BASE + '?page=2'))

        envelope = paginator.get_paginated_response(['a'])

        self.assertIsNone(envelope['previous'])
        self.assertIsNone(envelope['first_page'])
        self.assertEqual(envelope['next'], '/api/recipe/articles/?page=2')
        self.assertEqual(
            envelope['last_page'], '/api/recipe/articles/?page=4')
        self.assertEqual(list(envelope), ENVELOPE_KEYS)

    def test_the_closing_page_has_no_forward_links(self):
        paginator = CustomPagination(
            page(4, previous_link=BASE + '?page=3'))

        envelope = paginator.get_paginated_response(['z'])

        self.assertIsNone(envelope['next'])
        self.assertIsNone(envelope['last_page'])
        self.assertEqual(
            envelope['previous'], '/api/recipe/articles/?page=3')
        self.assertEqual(envelope['current_page'], 4)

    def test_a_single_page_result_set_carries_no_links_at_all(self):
        paginator = CustomPagination(page(1, count=2, num_pages=1))

        envelope = paginator.get_paginated_response(['a', 'b'])

        self.assertEqual(
            envelope,
            {
                'count': 2,
                'first_page': None,
                'last_page': None,
                'next': None,
                'previous': None,
                'last_page_number': 1,
                'current_page': 1,
                'results': ['a', 'b'],
            },
        )

    def test_a_page_without_link_attributes_reports_no_links(self):
        paginator = CustomPagination(
            SimpleNamespace(
                number=1,
                paginator=SimpleNamespace(count=0, num_pages=1),
            )
        )

        self.assertIsNone(paginator.get_next_link())
        self.assertIsNone(paginator.get_previous_link())
        self.assertEqual(paginator.get_paginated_response([])['results'], [])

    def test_a_paginator_built_without_a_page_holds_none(self):
        self.assertIsNone(CustomPagination().page)
