"""The staff-facing JSON API mounted under ``/api/user/admin/``.

Two things separate this router from the rest of the project and both are
asserted below.  It falls back to the settings-level authenticator list,
whose first entry advertises no scheme, so an anonymous caller is answered
``403`` without a ``WWW-Authenticate`` header rather than ``401``.  And its
analytics actions are declared ``allow_any``, so they answer an anonymous
caller too -- with a wider result set, because the per-user filter only
engages once a request carries an identity.
"""

from __future__ import annotations

import datetime

from starlette import status

from app.testing import APIClient, TestCase, get_user_model
from app.urls import reverse
from core.models import PageVisit, utcnow

ADMIN_ROOT_URL = '/api/user/admin/'
USERS_URL = reverse('user:admin:users-list')
PAGE_VISITS_URL = reverse('user:admin:page-visits-list')
STATISTICS_URL = PAGE_VISITS_URL + 'visitor_statistics/'
REFERRERS_URL = PAGE_VISITS_URL + 'referrer_analysis/'

NOT_AUTHENTICATED = {'detail': 'Giriş bilgileri verilmedi.'}
NOT_PERMITTED = {'detail': 'Bu işlemi yapmak için izniniz bulunmuyor.'}

LIST_KEYS = [
    'id', 'username', 'email', 'name', 'surname', 'image',
    'is_active', 'is_staff', 'is_ban', 'is_delete',
    'created_at', 'updated_at',
]
DETAIL_KEYS = [
    'id', 'username', 'email', 'name', 'surname', 'image', 'about_me',
    'is_active', 'is_staff', 'is_ban', 'is_delete',
    'created_at', 'updated_at',
]


class AdminRootTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_the_router_index_lists_its_two_collections(self):
        res = self.client.get(ADMIN_ROOT_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data,
            {
                'users': 'http://testserver/api/user/admin/users/',
                'page-visits':
                    'http://testserver/api/user/admin/page-visits/',
            },
        )

    def test_the_router_index_is_read_only(self):
        res = self.client.post(ADMIN_ROOT_URL, {})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"POST" metoduna izin verilmiyor.'})
        self.assertEqual(res['Allow'], 'GET, HEAD, OPTIONS')


class AdminUsersAccessTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            'uye@pythontr.com', '123qwe', is_active=True)

    def test_an_anonymous_caller_is_forbidden_and_offered_no_scheme(self):
        res = self.client.get(USERS_URL)

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertNotIn('WWW-Authenticate', res.headers)
        self.assertEqual(res.data, NOT_AUTHENTICATED)

    def test_a_signed_in_member_without_staff_rights_is_forbidden(self):
        self.client.force_authenticate(user=self.user)

        res = self.client.get(USERS_URL)

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data, NOT_PERMITTED)

    def test_the_page_visit_collection_is_gated_the_same_way(self):
        anonymous = self.client.get(PAGE_VISITS_URL)
        self.client.force_authenticate(user=self.user)
        member = self.client.get(PAGE_VISITS_URL)

        self.assertEqual(anonymous.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(anonymous.data, NOT_AUTHENTICATED)
        self.assertNotIn('WWW-Authenticate', anonymous.headers)
        self.assertEqual(member.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(member.data, NOT_PERMITTED)

    def test_granting_staff_rights_opens_the_collection(self):
        self.client.force_authenticate(user=self.user)
        self.user.is_staff = True

        res = self.client.get(USERS_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            [row['email'] for row in res.data], ['uye@pythontr.com'])


class AdminUsersListTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        base = utcnow() - datetime.timedelta(days=1)
        self.admin = get_user_model().objects.create_user(
            email='yonetici@pythontr.com',
            password='123qwe',
            name='Yonetici',
            is_active=True,
            is_staff=True,
            created_at=base,
        )
        self.alice = get_user_model().objects.create_user(
            email='ayse@pythontr.com',
            password='123qwe',
            name='Ayse',
            surname='Yilmaz',
            about_me='Merhaba, ben Ayse.',
            is_active=True,
            created_at=base + datetime.timedelta(seconds=1),
        )
        self.bob = get_user_model().objects.create_user(
            email='bora@pythontr.com',
            password='123qwe',
            name='Bora',
            surname='Kaya',
            is_active=False,
            is_ban=True,
            created_at=base + datetime.timedelta(seconds=2),
        )
        self.client.force_authenticate(user=self.admin)

    def emails(self, response):
        return [row['email'] for row in response.data]

    def test_the_newest_account_is_listed_first(self):
        res = self.client.get(USERS_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            self.emails(res),
            ['bora@pythontr.com', 'ayse@pythontr.com',
             'yonetici@pythontr.com'],
        )

    def test_a_listed_row_carries_the_published_fields_in_order(self):
        res = self.client.get(USERS_URL)

        row = res.data[1]
        self.assertEqual(list(row), LIST_KEYS)
        self.assertEqual(row['id'], self.alice.id)
        self.assertEqual(row['username'], 'ayse')
        self.assertEqual(row['name'], 'Ayse')
        self.assertEqual(row['surname'], 'Yilmaz')
        self.assertIsNone(row['image'])
        self.assertTrue(row['is_active'])
        self.assertFalse(row['is_staff'])
        self.assertTrue(row['created_at'].endswith('Z'))

    def test_the_list_withholds_the_biography(self):
        res = self.client.get(USERS_URL)

        self.assertNotIn('about_me', res.data[0])

    def test_search_matches_the_surname(self):
        res = self.client.get(USERS_URL, {'search': 'Yilmaz'})

        self.assertEqual(self.emails(res), ['ayse@pythontr.com'])

    def test_search_matches_the_name_without_regard_to_case(self):
        res = self.client.get(USERS_URL, {'search': 'bora'})

        self.assertEqual(self.emails(res), ['bora@pythontr.com'])

    def test_search_matches_a_fragment_of_the_address(self):
        res = self.client.get(USERS_URL, {'search': 'yonetici@'})

        self.assertEqual(self.emails(res), ['yonetici@pythontr.com'])

    def test_a_search_that_matches_nothing_lists_nothing(self):
        res = self.client.get(USERS_URL, {'search': 'zzzz'})

        self.assertEqual(res.data, [])

    def test_the_active_flag_filters_both_ways(self):
        active = self.client.get(USERS_URL, {'is_active': 'true'})
        passive = self.client.get(USERS_URL, {'is_active': 'false'})

        self.assertEqual(
            self.emails(active),
            ['ayse@pythontr.com', 'yonetici@pythontr.com'])
        self.assertEqual(self.emails(passive), ['bora@pythontr.com'])

    def test_the_staff_flag_accepts_the_numeric_spelling(self):
        staff = self.client.get(USERS_URL, {'is_staff': '1'})
        rest = self.client.get(USERS_URL, {'is_staff': '0'})

        self.assertEqual(self.emails(staff), ['yonetici@pythontr.com'])
        self.assertEqual(
            self.emails(rest),
            ['bora@pythontr.com', 'ayse@pythontr.com'])

    def test_the_ban_flag_filters_the_banned_account_out(self):
        banned = self.client.get(USERS_URL, {'is_ban': 'True'})
        clean = self.client.get(USERS_URL, {'is_ban': 'False'})

        self.assertEqual(self.emails(banned), ['bora@pythontr.com'])
        self.assertEqual(
            self.emails(clean),
            ['ayse@pythontr.com', 'yonetici@pythontr.com'])

    def test_an_unreadable_flag_value_is_ignored(self):
        res = self.client.get(USERS_URL, {'is_active': 'belki'})

        self.assertEqual(len(res.data), 3)

    def test_the_filters_combine_with_the_search(self):
        res = self.client.get(
            USERS_URL, {'search': 'pythontr.com', 'is_active': 'true',
                        'is_staff': 'false'})

        self.assertEqual(self.emails(res), ['ayse@pythontr.com'])

    def test_the_collection_only_answers_reads(self):
        res = self.client.post(USERS_URL, {'email': 'yeni@pythontr.com'})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"POST" metoduna izin verilmiyor.'})
        self.assertEqual(res['Allow'], 'GET')


class AdminUserDetailTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_user(
            email='yonetici@pythontr.com',
            password='123qwe',
            is_active=True,
            is_staff=True,
        )
        self.other = get_user_model().objects.create_user(
            email='ayse@pythontr.com',
            password='123qwe',
            name='Ayse',
            about_me='Merhaba, ben Ayse.',
            is_active=True,
        )
        self.client.force_authenticate(user=self.admin)

    def url(self, user):
        return reverse('user:admin:users-detail', args=[user.id])

    def test_the_detail_document_adds_the_biography(self):
        res = self.client.get(self.url(self.other))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(list(res.data), DETAIL_KEYS)
        self.assertEqual(res.data['about_me'], 'Merhaba, ben Ayse.')
        self.assertEqual(res.data['email'], 'ayse@pythontr.com')
        self.assertEqual(res.data['id'], self.other.id)

    def test_a_missing_row_raises_out_of_the_view(self):
        with self.assertRaises(get_user_model().DoesNotExist):
            self.client.get(
                reverse('user:admin:users-detail', args=[9999999]))

    def test_patching_another_account_returns_its_four_flags(self):
        res = self.client.patch(
            self.url(self.other),
            {'is_ban': True, 'is_active': False},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data,
            {'is_active': False, 'is_staff': False,
             'is_ban': True, 'is_delete': False},
        )
        self.session.refresh(self.other)
        self.assertTrue(self.other.is_ban)
        self.assertFalse(self.other.is_active)

    def test_a_flag_left_out_of_the_payload_is_left_alone(self):
        self.client.patch(
            self.url(self.other), {'is_staff': True}, format='json')

        self.session.refresh(self.other)
        self.assertTrue(self.other.is_staff)
        self.assertTrue(self.other.is_active)

    def test_an_administrator_may_not_modify_their_own_account(self):
        res = self.client.patch(
            self.url(self.admin), {'is_ban': True}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data, {'error': 'you_cannot_modify_your_own_account'})
        self.session.refresh(self.admin)
        self.assertFalse(self.admin.is_ban)

    def test_an_administrator_may_not_delete_their_own_account(self):
        res = self.client.delete(self.url(self.admin))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data, {'error': 'you_cannot_delete_your_own_account'})
        self.session.refresh(self.admin)
        self.assertFalse(self.admin.is_delete)

    def test_deleting_another_account_only_marks_it(self):
        res = self.client.delete(self.url(self.other))

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(res.content, b'')
        self.session.refresh(self.other)
        self.assertTrue(self.other.is_delete)
        self.assertEqual(
            self.session.get(get_user_model(), self.other.id), self.other)

    def test_a_deleted_account_is_still_listed(self):
        self.client.delete(self.url(self.other))

        res = self.client.get(USERS_URL)

        self.assertEqual(
            [row['is_delete'] for row in res.data
             if row['id'] == self.other.id],
            [True],
        )

    def test_the_detail_path_refuses_a_replacement(self):
        res = self.client.put(self.url(self.other), {})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"PUT" metoduna izin verilmiyor.'})
        self.assertEqual(res['Allow'], 'GET, PATCH, DELETE')


class PageVisitListTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            email='ziyaret@pythontr.com', password='123qwe')
        self.client.force_authenticate(user=self.admin)

    def test_a_recorded_visit_breaks_the_serializer(self):
        PageVisit.objects.create(
            user_id=self.admin.id, path='/makale/1-baslik',
            device_type='desktop')

        with self.assertRaises(AttributeError):
            self.client.get(PAGE_VISITS_URL)

    def test_the_collection_refuses_a_replacement(self):
        res = self.client.put(PAGE_VISITS_URL, {})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"PUT" metoduna izin verilmiyor.'})


class VisitorStatisticsTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            email='istatistik@pythontr.com', password='123qwe')
        self.stranger = get_user_model().objects.create_user(
            email='yabanci@pythontr.com', password='123qwe')
        self.moment = utcnow()
        self.visit(
            path='/makale/1', device_type='mobile', browser='Chrome',
            os='Mac OS X', ip_address='203.0.113.1',
            referrer='https://google.com')
        self.visit(
            path='/makale/1', device_type='desktop', browser='Chrome',
            os='Linux', ip_address='203.0.113.2',
            referrer='https://google.com')
        self.visit(
            path='/makale/2', device_type='desktop', browser='Firefox',
            os='Linux', ip_address='203.0.113.3', referrer='')
        self.foreign = PageVisit.objects.create(
            user_id=self.stranger.id, path='/hakkimizda',
            device_type='desktop', browser='Safari', os='iOS',
            ip_address='203.0.113.9', referrer='https://bing.com',
            timestamp=self.moment,
        )

    def visit(self, **fields):
        fields.setdefault('timestamp', self.moment)
        return PageVisit.objects.create(user_id=self.admin.id, **fields)

    def test_the_document_carries_every_published_section(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(STATISTICS_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            list(res.data),
            ['period_info', 'total_visits', 'device_distribution',
             'browser_distribution', 'os_distribution',
             'most_visited_pages', 'traffic_by_hour'],
        )
        self.assertEqual(
            res.data['period_info'],
            {'period': 'all', 'start_date': None, 'end_date': None},
        )

    def test_an_identified_caller_only_sees_their_own_visits(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(STATISTICS_URL)

        self.assertEqual(res.data['total_visits'], 3)
        self.assertEqual(
            res.data['device_distribution'],
            [{'device_type': 'desktop', 'count': 2},
             {'device_type': 'mobile', 'count': 1}],
        )
        self.assertEqual(
            res.data['browser_distribution'],
            [{'browser': 'Chrome', 'count': 2},
             {'browser': 'Firefox', 'count': 1}],
        )
        self.assertEqual(
            res.data['os_distribution'],
            [{'os': 'Linux', 'count': 2},
             {'os': 'Mac OS X', 'count': 1}],
        )
        self.assertEqual(
            res.data['most_visited_pages'],
            [{'path': '/makale/1', 'visit_count': 2},
             {'path': '/makale/2', 'visit_count': 1}],
        )

    def test_an_anonymous_caller_reaches_the_action_and_sees_everything(
            self):
        res = self.client.get(STATISTICS_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data['total_visits'], 4)
        self.assertIn(
            {'path': '/hakkimizda', 'visit_count': 1},
            res.data['most_visited_pages'],
        )

    def test_visits_recorded_at_one_instant_share_one_traffic_bucket(self):
        self.client.force_authenticate(user=self.admin)

        traffic = self.client.get(STATISTICS_URL).data['traffic_by_hour']

        self.assertEqual(len(traffic), 1)
        self.assertEqual(traffic[0]['count'], 3)
        self.assertIn(traffic[0]['hour'], range(24))

    def test_the_month_window_leaves_an_older_visit_out(self):
        self.visit(
            path='/eski', device_type='desktop', browser='Chrome',
            os='Linux', ip_address='203.0.113.4',
            timestamp=self.moment - datetime.timedelta(days=60),
        )
        self.client.force_authenticate(user=self.admin)

        month = self.client.get(STATISTICS_URL, {'period': 'month'})
        every = self.client.get(STATISTICS_URL)

        self.assertEqual(
            month.data['period_info'],
            {'period': 'month', 'start_date': None, 'end_date': None},
        )
        self.assertEqual(month.data['total_visits'], 3)
        self.assertEqual(every.data['total_visits'], 4)
        self.assertNotIn(
            {'path': '/eski', 'visit_count': 1},
            month.data['most_visited_pages'],
        )

    def test_the_action_is_read_only(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.post(STATISTICS_URL, {})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"POST" metoduna izin verilmiyor.'})


class ReferrerAnalysisTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            email='kaynak@pythontr.com', password='123qwe')
        self.moment = utcnow()
        self.visit(referrer='https://google.com', ip_address='203.0.113.1')
        self.visit(referrer='https://google.com', ip_address='203.0.113.2')
        self.visit(referrer='https://bing.com', ip_address='203.0.113.3')
        self.visit(referrer='', ip_address='203.0.113.4')
        self.visit(referrer=None, ip_address='203.0.113.5')

    def visit(self, **fields):
        return PageVisit.objects.create(
            user_id=self.admin.id,
            path='/makale/1',
            device_type='desktop',
            timestamp=self.moment,
            **fields
        )

    def test_referrers_are_counted_and_ranked(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(REFERRERS_URL)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(list(res.data), ['period_info', 'referrers'])
        self.assertEqual(
            res.data['referrers'],
            [
                {'referrer': 'https://google.com', 'visit_count': 2,
                 'unique_visitors': 2},
                {'referrer': 'https://bing.com', 'visit_count': 1,
                 'unique_visitors': 1},
            ],
        )

    def test_a_repeated_visitor_counts_once_towards_unique(self):
        self.visit(referrer='https://bing.com', ip_address='203.0.113.3')
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(REFERRERS_URL)

        rows = {row['referrer']: row for row in res.data['referrers']}
        self.assertEqual(
            rows['https://bing.com'],
            {'referrer': 'https://bing.com', 'visit_count': 2,
             'unique_visitors': 1},
        )

    def test_the_reported_period_echoes_the_query(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(
            REFERRERS_URL,
            {'period': 'year', 'start_date': '2020-01-01'})

        self.assertEqual(
            res.data['period_info'],
            {'period': 'year', 'start_date': '2020-01-01',
             'end_date': None},
        )
        self.assertEqual(len(res.data['referrers']), 2)

    def test_the_action_is_read_only(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.delete(REFERRERS_URL)

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"DELETE" metoduna izin verilmiyor.'})


class PageVisitWriteTests(TestCase):
    """The collection's write half, which the analytics actions hide.

    The baseline registers this collection from a full model viewset, so
    ``POST`` and ``OPTIONS`` are advertised and reachable even though the
    serializer behind them names a column the model does not have.  Both
    verbs describe the field map before they look at the request, so both
    hit that defect rather than answering ``405`` -- and the difference
    between the two matters, because ``405`` would tell a caller the route
    does not accept writes when in fact it does.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            email='yazan@pythontr.com', password='123qwe')

    def test_the_collection_advertises_the_write_verbs(self):
        res = self.client.get(PAGE_VISITS_URL)

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res['Allow'], 'GET, POST, HEAD, OPTIONS')

    def test_an_anonymous_write_is_refused_before_the_serializer(self):
        res = self.client.post(PAGE_VISITS_URL, {})

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data, NOT_AUTHENTICATED)

    def test_an_anonymous_options_is_refused_too(self):
        res = self.client.options(PAGE_VISITS_URL)

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data, NOT_AUTHENTICATED)

    def test_a_write_reaches_the_broken_serializer(self):
        self.client.force_authenticate(user=self.admin)

        with self.assertRaises(AttributeError):
            self.client.post(PAGE_VISITS_URL, {'path': '/makale/1'})

    def test_describing_the_collection_reaches_it_as_well(self):
        self.client.force_authenticate(user=self.admin)

        with self.assertRaises(AttributeError):
            self.client.options(PAGE_VISITS_URL)


class PageVisitDetailTests(TestCase):
    """The record routes the collection's viewset also registers.

    Every one of them is staff-only, and the check runs before the lookup,
    so an anonymous caller cannot learn whether a record exists.  For a
    caller who is staff the outcome splits three ways: a record that is
    there reaches the broken serializer, a numeric id that is not there
    answers the baseline's untranslated ``get_object_or_404`` sentence, and
    an id that is not a number answers the generic message instead --
    because the lookup raises before the query is built.  ``DELETE`` is the
    only verb that completes, since it never describes a field.
    """

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_superuser(
            email='kayit@pythontr.com', password='123qwe')
        self.visit = PageVisit.objects.create(
            user_id=self.admin.id, path='/makale/1-baslik',
            device_type='desktop')
        self.url = '{}{}/'.format(PAGE_VISITS_URL, self.visit.id)
        self.missing_url = '{}{}/'.format(PAGE_VISITS_URL, 10 ** 9)

    def test_an_anonymous_read_is_forbidden(self):
        res = self.client.get(self.url)

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data, NOT_AUTHENTICATED)

    def test_an_anonymous_delete_is_forbidden_before_the_lookup(self):
        res = self.client.delete(self.missing_url)

        self.assertEqual(res.status_code, status.HTTP_403_FORBIDDEN)
        self.assertEqual(res.data, NOT_AUTHENTICATED)

    def test_the_record_advertises_the_full_verb_set(self):
        res = self.client.get(self.url)

        self.assertEqual(
            res['Allow'], 'GET, PUT, PATCH, DELETE, HEAD, OPTIONS')

    def test_reading_a_record_reaches_the_broken_serializer(self):
        self.client.force_authenticate(user=self.admin)

        with self.assertRaises(AttributeError):
            self.client.get(self.url)

    def test_replacing_a_record_reaches_it_too(self):
        self.client.force_authenticate(user=self.admin)

        with self.assertRaises(AttributeError):
            self.client.put(self.url, {'path': '/x'})

    def test_a_record_refuses_to_be_created_at_its_own_address(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.post(self.url, {})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"POST" metoduna izin verilmiyor.'})

    def test_deleting_a_record_answers_no_content(self):
        # That the row is really gone afterwards cannot be asserted here:
        # a request ends the transaction the fixture was created in, so a
        # second request sees an empty table whatever the first one did.
        # The probe matrix checks the deletion itself against the database.
        self.client.force_authenticate(user=self.admin)

        res = self.client.delete(self.url)

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertEqual(res.content, b'')
        self.assertNotIn('Content-Type', res.headers)

    def test_a_missing_record_answers_the_untranslated_sentence(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(self.missing_url)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            res.data, {'detail': 'No PageVisit matches the given query.'})

    def test_deleting_a_missing_record_answers_the_same(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.delete(self.missing_url)

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(
            res.data, {'detail': 'No PageVisit matches the given query.'})

    def test_a_lookup_that_is_not_a_number_answers_the_generic_message(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.get(PAGE_VISITS_URL + 'abc/')

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertEqual(res.data, {'detail': 'Bulunamadı.'})

    def test_describing_a_missing_record_answers_its_metadata(self):
        self.client.force_authenticate(user=self.admin)

        res = self.client.options(self.missing_url)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data,
            {
                'name': 'Page Visit Instance',
                'description': '',
                'renders': ['application/json', 'text/html'],
                'parses': [
                    'application/json',
                    'application/x-www-form-urlencoded',
                    'multipart/form-data',
                ],
            },
        )

    def test_describing_a_record_that_exists_reaches_the_serializer(self):
        self.client.force_authenticate(user=self.admin)

        with self.assertRaises(AttributeError):
            self.client.options(self.url)
