"""Behaviour the port is required to keep wrong.

Every case here is a defect the original shipped and the migration was told
to reproduce rather than repair, listed in ``PORT_PLAN.md`` section 5.  The
source suite never covered any of them, so without these tests a later
"fix" would look like an improvement and silently break parity.
"""

import json

from app.testing import APIClient, TestCase, get_user_model
from app.urls import reverse
from core.models import (
    CONTENT_TYPE_IDS,
    DEVICE_TYPE_CHOICES,
    Category,
    PageVisit,
    Token,
    article_image_file_path,
    slider_image_file_path,
)

PAGE_VISITS_URL = reverse('user:admin:page-visits-list')
CONTENT_PERFORMANCE_URL = PAGE_VISITS_URL + 'content_performance/'
ME_URL = reverse('user:me')


class PreservedDefectTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_user_save_walks_the_slug_forward(self):
        user = get_user_model().objects.create_user(
            'drift@pythontr.com', '123qwe')
        first = user.slug

        user.save()

        self.assertEqual(first, 'drift')
        self.assertEqual(user.slug, 'drift-1')

    def test_missing_category_raises_out_of_the_view(self):
        with self.assertRaises(Category.DoesNotExist):
            self.client.get(
                reverse('recipe:category-detail', args=['yok-boyle-bir-slug']))

    def test_content_performance_averages_a_column_that_is_not_there(self):
        self.client.force_authenticate(
            get_user_model().objects.create_superuser(
                'perf@pythontr.com', '123qwe'))

        with self.assertRaises(AttributeError):
            self.client.get(CONTENT_PERFORMANCE_URL)

    def test_page_visit_list_is_empty_but_successful(self):
        self.client.force_authenticate(
            get_user_model().objects.create_superuser(
                'visits@pythontr.com', '123qwe'))

        res = self.client.get(PAGE_VISITS_URL)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res.data, [])

    def test_cookie_token_authentication_never_authenticates(self):
        user = get_user_model().objects.create_user(
            'cookie@pythontr.com', '123qwe', is_active=True)
        token = Token(user_id=user.id)
        token.save(self.session)
        self.client.cookies.set('session', json.dumps({'token': token.key}))

        res = self.client.get(ME_URL)

        self.assertEqual(res.status_code, 401)
        self.assertEqual(res.data, {'detail': 'Giriş bilgileri verilmedi.'})

    def test_create_user_error_formats_the_value_not_the_field(self):
        with self.assertRaises(ValueError) as caught:
            get_user_model().objects.create_user(None, '123qwe')

        self.assertEqual(
            str(caught.exception), 'Users must have an None address')

    def test_slider_image_path_keeps_its_doubled_slash(self):
        path = slider_image_file_path(None, 'gorsel.png')

        self.assertEqual(path, 'static/img//gorsel.png')

    def test_article_image_path_rejects_a_second_dot(self):
        with self.assertRaises(ValueError):
            article_image_file_path(None, 'arsiv.tar.gz')

    def test_page_visit_device_type_defaults_outside_its_own_choices(self):
        default = PageVisit.__table__.c.device_type.default.arg

        self.assertEqual(default, 'unknown')
        self.assertNotIn(default, DEVICE_TYPE_CHOICES)

    def test_content_type_identifiers_are_frozen(self):
        stored = {
            '{}.{}'.format(app_label, model): pk
            for pk, app_label, model in CONTENT_TYPE_IDS
        }

        self.assertEqual(stored['core.article'], 10)
        self.assertEqual(stored['core.comment'], 11)
        self.assertEqual(len(CONTENT_TYPE_IDS), 15)

    def test_reset_password_confirm_is_registered_twice(self):
        bare = reverse('user:reset-password-confirm')
        linked = reverse('user:reset-password-confirm', args=['YWJj', 'tok'])

        self.assertEqual(bare, '/api/user/reset-password/confirm/')
        self.assertEqual(linked, '/api/user/reset-password/confirm/YWJj/tok/')
