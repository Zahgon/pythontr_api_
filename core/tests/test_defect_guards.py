"""Behaviour the rest of the suite left unguarded.

Each test here was written because a deliberate one-line defect injected into
the implementation went undetected by every other module.  They close the
mutation-coverage holes rather than restating assertions made elsewhere.
"""

from unittest.mock import patch

from starlette.requests import Request

from app import wire
from app.testing import APIClient, TestCase
from app.urls import reverse
from core.models import Article, Category, Message, User


ARTICLES_URL = reverse('recipe:article-list')
CREATE_USER_URL = reverse('user:create')
CATEGORIES_URL = reverse('recipe:category-list')
MESSAGES_URL = reverse('recipe:message-list')


def _request(path=CATEGORIES_URL, query=b''):
    return Request({
        'type': 'http',
        'method': 'GET',
        'path': path,
        'raw_path': path.encode('utf-8'),
        'query_string': query,
        'headers': [(b'host', b'testserver')],
        'scheme': 'http',
        'server': ('testserver', 80),
        'client': ('testclient', 50000),
        'root_path': '',
    })


class CategoryChainSeparatorTests(TestCase):
    """``full_category_name`` is published verbatim in every category body."""

    def test_the_parent_chain_is_joined_with_a_spaced_slash(self):
        parent = Category.objects.create(
            name='Ust Kategori', title='Ust Baslik', title_h1='Ust H1',
            short_name='ust',
        )
        child = Category.objects.create(
            name='Alt Kategori', title='Alt Baslik', title_h1='Alt H1',
            short_name='alt', parent_category=parent,
        )

        self.assertEqual(parent.full_category_name, 'Ust Kategori')
        self.assertEqual(child.full_category_name, 'Ust Kategori / Alt Kategori')

    def test_the_separator_reaches_the_serialised_body(self):
        parent = Category.objects.create(
            name='Kok', title='Kok Baslik', title_h1='Kok H1', short_name='kok',
        )
        child = Category.objects.create(
            name='Dal', title='Dal Baslik', title_h1='Dal H1',
            short_name='dal', parent_category=parent,
        )

        res = APIClient().get('%s%s/' % (CATEGORIES_URL, child.id))

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data['full_category_name'], 'Kok / Dal')


class AnonymousArticleVisibilityTests(TestCase):
    """An anonymous list is forced to active rows only."""

    def setUp(self):
        self.client = APIClient()
        self.user = User.objects.create_user(
            email='visibility@pythontr.com',
            password='testpass123',
            username='visibility',
        )

    def test_an_inactive_article_is_hidden_from_the_anonymous_list(self):
        Article.objects.create(
            title='Yayindaki Makale', title_h1='Yayindaki Makale',
            description='aciklama', content='icerik',
            user=self.user, is_active=True,
        )
        Article.objects.create(
            title='Taslak Makale', title_h1='Taslak Makale',
            description='aciklama', content='icerik',
            user=self.user, is_active=False,
        )

        res = self.client.get(ARTICLES_URL)

        self.assertEqual(res.status_code, 200)
        titles = [row['title'] for row in res.data]
        self.assertIn('Yayindaki Makale', titles)
        self.assertNotIn('Taslak Makale', titles)


class StaffEscalationTests(TestCase):
    """Account creation refuses to honour a staff flag from the payload."""

    def test_a_payload_asking_for_staff_still_creates_a_plain_account(self):
        payload = {
            'email': 'escalate@pythontr.com',
            'password': 'testpass123',
            'confirm_password': 'testpass123',
            'username': 'escalate',
            'is_staff': True,
        }

        res = APIClient().post(CREATE_USER_URL, payload)

        self.assertEqual(res.status_code, 201)
        self.assertFalse(res.data['is_staff'])
        created = User.objects.get(email='escalate@pythontr.com')
        self.assertFalse(created.is_staff)


class PaginationEnvelopeTests(TestCase):
    """The envelope key order is part of the published contract."""

    def test_the_envelope_keys_are_in_the_published_order(self):
        with patch.object(wire, 'page_size', return_value=2):
            envelope = wire.paginate(_request(), [1, 2, 3, 4, 5])

        self.assertEqual(
            list(envelope),
            ['count', 'first_page', 'last_page', 'next', 'previous',
             'last_page_number', 'current_page', 'results'],
        )
        self.assertEqual(envelope['count'], 5)
        self.assertEqual(envelope['last_page_number'], 3)
        self.assertEqual(envelope['current_page'], 1)
        self.assertEqual(envelope['results'], [1, 2])

    def test_a_later_page_reports_its_own_position(self):
        with patch.object(wire, 'page_size', return_value=2):
            envelope = wire.paginate(_request(query=b'page=3'), [1, 2, 3, 4, 5])

        self.assertEqual(envelope['current_page'], 3)
        self.assertEqual(envelope['last_page_number'], 3)
        self.assertEqual(envelope['results'], [5])


class MessageVisibilityTests(TestCase):
    """A conversation is visible to both of its parties, not only the receiver."""

    def setUp(self):
        self.client = APIClient()
        self.sender = User.objects.create_user(
            email='sender@pythontr.com', password='pass12345',
            username='sender', is_active=True,
        )
        self.receiver = User.objects.create_user(
            email='receiver@pythontr.com', password='pass12345',
            username='receiver', is_active=True,
        )

    def test_a_sent_message_is_visible_to_its_sender(self):
        Message.objects.create(
            subject='Gonderilen', content='govde', ip='127.0.0.1',
            sender=self.sender, user=self.receiver,
        )
        self.client.force_authenticate(user=self.sender)

        res = self.client.get(MESSAGES_URL)

        self.assertEqual(res.status_code, 200)
        self.assertEqual([row['subject'] for row in res.data], ['Gonderilen'])

    def test_the_outbox_filter_still_reports_sent_messages(self):
        Message.objects.create(
            subject='Giden', content='govde', ip='127.0.0.1',
            sender=self.sender, user=self.receiver,
        )
        self.client.force_authenticate(user=self.sender)

        res = self.client.get(MESSAGES_URL, {'outbox': '1'})

        self.assertEqual(res.status_code, 200)
        self.assertEqual([row['subject'] for row in res.data], ['Giden'])
