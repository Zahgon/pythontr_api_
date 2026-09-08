"""An explicit JSON ``null`` is a validation error, not a crash.

The baseline runs ``Field.validate_empty_values`` on every supplied field
before it looks at the type, so a field declared without ``allow_null``
answers ``This field may not be null.`` and the write never reaches the
database.  Nothing in the port noticed that rule until now: an explicit
null went straight through the schema into the session and the column
constraint turned it into a 500.  The cases below pin the whole contract
down - which fields accept a null, which refuse it, the order the refusals
come back in, and the fact that a refused null reads as a null and not as
a type error.
"""

from starlette import status

from app.testing import APIClient, TestCase, get_user_model
from app.urls import reverse

from core.models import Article, Category, ContentType
from core.models import Slider, content_type_id_for

#: The message both the null and the blank rule carry in the Turkish
#: catalogue - the upstream translation maps the two keys to one string.
NULL = 'Bu alan boş bırakılmamalı.'

#: What a field that was left out of a full update answers with.
REQUIRED = 'Bu alan zorunlu.'

CATEGORIES_URL = reverse('recipe:category-list')
COMMENT_URL = reverse('recipe:comment-list')
MESSAGE_URL = reverse('recipe:message-list')
ME_URL = reverse('user:me')
TOKEN_URL = reverse('user:token')
CREATE_USER_URL = reverse('user:create')
RESET_URL = reverse('user:reset-password')
RESET_CONFIRM_URL = reverse('user:reset-password-confirm')
RESEND_URL = reverse('user:resend-activation')


class CategoryNullTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'null-category@pythontr.com', '123qwe')
        self.category = Category.objects.create(
            user=self.user, name='python programlama',
            title='tikla ve ogren', title_h1='Python', short_name='python')
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse(
            'recipe:category-detail', args=[self.category.id])

    def test_a_null_on_a_non_nullable_field_is_refused(self):
        res = self.client.patch(
            self.url, {'short_name': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'short_name': [NULL]})

    def test_several_nulls_come_back_in_the_declared_order(self):
        res = self.client.patch(
            self.url,
            {'short_name': None, 'name': None, 'title': None},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(list(res.data), ['name', 'title', 'short_name'])
        self.assertEqual(res.data['name'], [NULL])

    def test_a_full_update_reports_the_missing_fields_and_the_null(self):
        res = self.client.put(
            self.url, {'short_name': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {
                'name': [REQUIRED],
                'title': [REQUIRED],
                'title_h1': [REQUIRED],
                'short_name': [NULL],
            },
        )

    def test_a_null_on_a_nullable_text_field_is_accepted(self):
        res = self.client.patch(
            self.url, {'description': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)

    def test_a_null_clears_the_nullable_parent_relation(self):
        res = self.client.patch(
            self.url, {'parent_category': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)


class SliderNullTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'null-slider@pythontr.com', '123qwe', is_staff=True)
        self.slider = Slider.objects.create(
            title='How to update for dictionary',
            description='Bla bla bla',
            link='https://www.pythontr.com',
            is_active=True,
        )
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse('recipe:slider-detail', args=[self.slider.id])

    def test_a_null_flag_is_refused(self):
        res = self.client.patch(
            self.url, {'is_approval': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'is_approval': [NULL]})

    def test_only_the_non_nullable_field_of_the_three_is_refused(self):
        res = self.client.patch(
            self.url,
            {'title': None, 'link': None, 'approval_user': None},
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'title': [NULL]})


class ArticleNullTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'null-article@pythontr.com', '123qwe', is_staff=True)
        self.category = Category.objects.create(
            user=self.user, name='veritabani mysql',
            title='Veritabani', title_h1='Veritabani', short_name='mysql')
        self.article = Article.objects.create(
            title='Pythontr.Com on BBC',
            title_h1='Do you hear us? Pythontr...',
            description='bla bla....',
            content='bla bla....bla......',
            is_active=True,
        )
        self.article.categories.append(self.category)
        self.client = APIClient()
        self.client.force_authenticate(self.user)
        self.url = reverse('recipe:article-detail', args=[self.article.id])

    def test_every_non_nullable_field_in_the_payload_is_refused(self):
        res = self.client.patch(
            self.url,
            {
                'description': None,
                'content': None,
                'is_active': None,
                'is_delete': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {
                'description': [NULL],
                'content': [NULL],
                'is_active': [NULL],
                'is_delete': [NULL],
            },
        )

    def test_a_null_on_the_relation_is_refused(self):
        res = self.client.patch(
            self.url, {'categories': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'categories': [NULL]})

    def test_a_null_image_is_accepted(self):
        res = self.client.patch(self.url, {'image': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_200_OK)


class CommentNullTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.article = Article.objects.create(
            title='Pythontr.Com on BBC',
            title_h1='Do you hear us? Pythontr...',
            description='bla bla....',
            content='bla bla....bla......',
            is_active=True,
        )
        self.content_type = ContentType.objects.get(
            id=content_type_id_for('article'))

    def test_an_all_null_comment_refuses_every_field_but_the_author(self):
        res = self.client.post(
            COMMENT_URL,
            {
                'content': None, 'email': None, 'name': None, 'ip': None,
                'user': None, 'content_type': None, 'object_id': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            list(res.data),
            ['content', 'email', 'name', 'ip', 'content_type', 'object_id'],
        )
        self.assertEqual(res.data['content'], [NULL])


class MessageNullTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'null-message@pythontr.com', '123qwe')
        self.client = APIClient()
        self.client.force_authenticate(self.user)

    def test_an_all_null_message_refuses_every_field_but_the_parties(self):
        res = self.client.post(
            MESSAGE_URL,
            {
                'sender': None, 'user': None, 'subject': None,
                'content': None, 'ip': None, 'is_read': None,
                'is_delete': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            list(res.data),
            ['subject', 'content', 'ip', 'is_read', 'is_delete'],
        )
        self.assertEqual(res.data['subject'], [NULL])


class UserNullTests(TestCase):

    def setUp(self):
        self.user = get_user_model().objects.create_user(
            'null-user@pythontr.com', '123qwe')
        self.client = APIClient()

    def test_creating_an_account_out_of_nulls_refuses_all_but_the_image(self):
        res = self.client.post(
            CREATE_USER_URL,
            {
                'email': None, 'password': None, 'confirm_password': None,
                'username': None, 'name': None, 'image': None,
                'about_me': None, 'is_notification_email': None,
                'is_staff': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            list(res.data),
            [
                'email', 'password', 'confirm_password', 'username',
                'name', 'about_me', 'is_notification_email', 'is_staff',
            ],
        )
        self.assertEqual(res.data['email'], [NULL])

    def test_the_optional_profile_fields_still_refuse_a_null(self):
        res = self.client.post(
            CREATE_USER_URL,
            {
                'surname': None, 'linkedin': None, 'github': None,
                'current_password': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {
                'email': [REQUIRED],
                'password': [REQUIRED],
                'username': [REQUIRED],
                'surname': [NULL],
                'linkedin': [NULL],
                'github': [NULL],
                'current_password': [NULL],
            },
        )

    def test_a_partial_profile_update_still_refuses_the_nulls(self):
        self.client.force_authenticate(self.user)

        res = self.client.patch(
            ME_URL,
            {
                'username': None, 'name': None, 'image': None,
                'is_notification_email': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {
                'username': [NULL],
                'name': [NULL],
                'is_notification_email': [NULL],
            },
        )

    def test_asking_for_a_token_with_nulls_is_refused(self):
        res = self.client.post(
            TOKEN_URL, {'email': None, 'password': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'email': [NULL], 'password': [NULL]})


class PasswordResetNullTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_a_null_address_is_refused_by_the_reset_request(self):
        res = self.client.post(RESET_URL, {'email': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'email': [NULL]})

    def test_an_all_null_confirmation_refuses_every_field(self):
        res = self.client.post(
            RESET_CONFIRM_URL,
            {
                'password': None, 'confirm_password': None,
                'token': None, 'uidb64': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {
                'password': [NULL],
                'confirm_password': [NULL],
                'token': [NULL],
                'uidb64': [NULL],
            },
        )

    def test_a_null_address_is_refused_by_the_activation_resend(self):
        res = self.client.post(RESEND_URL, {'email': None}, format='json')

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'email': [NULL]})


class AdminUserActionNullTests(TestCase):

    def setUp(self):
        self.client = APIClient()
        self.admin = get_user_model().objects.create_user(
            email='null-admin@pythontr.com', password='123qwe',
            is_active=True, is_staff=True)
        self.other = get_user_model().objects.create_user(
            email='null-other@pythontr.com', password='123qwe',
            is_active=True)
        self.client.force_authenticate(user=self.admin)

    def test_every_null_flag_is_refused(self):
        res = self.client.patch(
            reverse('user:admin:users-detail', args=[self.other.id]),
            {
                'is_active': None, 'is_staff': None,
                'is_ban': None, 'is_delete': None,
            },
            format='json',
        )

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {
                'is_active': [NULL],
                'is_staff': [NULL],
                'is_ban': [NULL],
                'is_delete': [NULL],
            },
        )
