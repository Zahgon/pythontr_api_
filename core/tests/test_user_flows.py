"""The public account endpoints the existing suite leaves untested.

Account creation, token issue and ``/me/`` are already covered by
``user/tests/test_user_api.py``.  What is not covered is everything that
happens by e-mail: activation, re-activation and the two halves of the
password reset exchange.  Those are driven here through the real ASGI
application, and the in-memory outbox is asserted alongside the response
because the mail is half of the observable behaviour.
"""

from __future__ import annotations

import datetime
import uuid

from starlette import status

from app import mail, settings
from app.security import default_token_generator, urlsafe_base64_encode
from app.testing import APIClient, TestCase, get_user_model
from app.urls import reverse
from core.models import ActivationCode, utcnow

RESEND_URL = reverse('user:resend-activation')
RESET_URL = reverse('user:reset-password')
RESET_CONFIRM_URL = reverse('user:reset-password-confirm')


def uid_of(user):
    return urlsafe_base64_encode(str(user.pk).encode('utf-8'))


class MailboxTestCase(TestCase):
    """Base class that isolates :data:`app.mail.outbox` per test."""

    def setUp(self):
        self.client = APIClient()
        self._saved_outbox = list(mail.outbox)
        del mail.outbox[:]
        self.addCleanup(self._restore_outbox)

    def _restore_outbox(self):
        mail.outbox[:] = self._saved_outbox


class ActivateUserTests(MailboxTestCase):

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            email='aktivasyon@pythontr.com',
            password='123qwe',
        )
        self.activation = ActivationCode.create_activation_code(
            self.user, session=self.session)

    def url(self, code):
        return reverse('user:activate', args=[code])

    def test_a_valid_code_activates_the_account(self):
        self.assertFalse(self.user.is_active)

        res = self.client.get(self.url(self.activation.code))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data, {'message': 'account_activated_successfully'})
        self.session.refresh(self.user)
        self.session.refresh(self.activation)
        self.assertTrue(self.user.is_active)
        self.assertTrue(self.activation.is_used)

    def test_a_code_may_not_be_spent_twice(self):
        self.client.get(self.url(self.activation.code))

        res = self.client.get(self.url(self.activation.code))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'activation_code_is_invalid'})

    def test_an_expired_code_is_refused_and_leaves_the_account_alone(self):
        expired = ActivationCode(
            user_id=self.user.id,
            code=uuid.uuid4(),
            expires_at=utcnow() - datetime.timedelta(minutes=1),
            is_used=False,
        )
        expired.save(session=self.session)

        res = self.client.get(self.url(expired.code))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'activation_code_is_expired'})
        self.session.refresh(self.user)
        self.assertFalse(self.user.is_active)

    def test_an_unknown_code_is_refused(self):
        res = self.client.get(self.url(uuid.uuid4()))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'activation_code_is_invalid'})
        self.session.refresh(self.user)
        self.assertFalse(self.user.is_active)

    def test_a_segment_that_is_not_a_uuid_never_reaches_the_view(self):
        res = self.client.get(self.url('bir-uuid-degil'))

        self.assertEqual(res.status_code, status.HTTP_404_NOT_FOUND)
        self.assertIn('Page not found', res.text)
        self.assertNotIn('Allow', res.headers)

    def test_the_activation_path_only_answers_reads(self):
        res = self.client.post(self.url(self.activation.code), {})

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"POST" metoduna izin verilmiyor.'})
        self.assertEqual(res['Allow'], 'GET, HEAD, OPTIONS')


class ResendActivationTests(MailboxTestCase):

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            email='tekrar@pythontr.com',
            password='123qwe',
        )
        self.original = ActivationCode.create_activation_code(
            self.user, session=self.session)

    def codes(self):
        return ActivationCode.objects.filter(user_id=self.user.id).all()

    def test_a_known_inactive_account_is_issued_a_fresh_code(self):
        res = self.client.post(
            RESEND_URL, {'email': self.user.email})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {'message': 'new_activation_code_sent'})
        codes = self.codes()
        unused = [code for code in codes if not code.is_used]
        self.assertEqual(len(codes), 2)
        self.assertEqual(len(unused), 1)
        self.assertNotEqual(unused[0].code, self.original.code)

    def test_the_new_code_is_mailed_to_the_account(self):
        self.client.post(RESEND_URL, {'email': self.user.email})

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'new_activation_code_title')
        self.assertEqual(message.recipients, [self.user.email])
        self.assertEqual(message.from_email, settings.DEFAULT_FROM_EMAIL)

    def test_an_unknown_address_is_refused(self):
        res = self.client.post(
            RESEND_URL, {'email': 'yok@pythontr.com'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data, {'error': 'user_not_found_with_active_code'})
        self.assertEqual(mail.outbox, [])

    def test_an_account_that_is_already_active_is_refused(self):
        self.user.is_active = True
        self.user.save(session=self.session)

        res = self.client.post(
            RESEND_URL, {'email': self.user.email})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data, {'error': 'user_not_found_with_active_code'})

    def test_a_missing_address_is_reported_as_a_field_error(self):
        res = self.client.post(RESEND_URL, {})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'email': ['Bu alan zorunlu.']})

    def test_a_malformed_address_is_reported_as_a_field_error(self):
        res = self.client.post(RESEND_URL, {'email': 'pythontr'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {'email': ['Geçerli bir e-posta adresi girin.']})


class ResetPasswordTests(MailboxTestCase):

    def setUp(self):
        super().setUp()
        self.user = get_user_model().objects.create_user(
            email='sifirla@pythontr.com',
            password='123qwe',
            is_active=True,
        )

    def test_a_known_address_is_told_the_link_went_out(self):
        res = self.client.post(RESET_URL, {'email': self.user.email})

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data,
            {'message': 'password_reset_success_message_link_sent'})

    def test_the_link_is_mailed_to_the_account(self):
        self.client.post(RESET_URL, {'email': self.user.email})

        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'password_reset_title')
        self.assertEqual(message.recipients, [self.user.email])

    def test_an_unknown_address_answers_a_nested_field_error(self):
        res = self.client.post(RESET_URL, {'email': 'yok@pythontr.com'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'email': {'error': 'email_not_found'}})
        self.assertEqual(mail.outbox, [])

    def test_a_missing_address_is_reported_as_a_field_error(self):
        res = self.client.post(RESET_URL, {})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'email': ['Bu alan zorunlu.']})


class ResetPasswordLinkCheckTests(TestCase):
    """``GET /api/user/reset-password/confirm/<uidb64>/<token>/``."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            email='baglanti@pythontr.com',
            password='123qwe',
            is_active=True,
        )
        self.uidb64 = uid_of(self.user)
        self.token = default_token_generator.make_token(self.user)

    def url(self, uidb64, token):
        return reverse(
            'user:reset-password-confirm', args=[uidb64, token])

    def test_a_fresh_link_reports_itself_valid(self):
        res = self.client.get(self.url(self.uidb64, self.token))

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(res.data, {'valid': True})

    def test_a_uid_that_decodes_to_nobody_is_an_invalid_link(self):
        missing = urlsafe_base64_encode(b'99999999')

        res = self.client.get(self.url(missing, self.token))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'invalid_link'})

    def test_a_uid_that_is_not_a_number_is_an_invalid_link(self):
        res = self.client.get(
            self.url(urlsafe_base64_encode(b'abc'), self.token))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'invalid_link'})

    def test_a_valid_uid_with_a_forged_token_is_refused(self):
        res = self.client.get(self.url(self.uidb64, 'sahte-imza'))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'invalid_token_or_expired'})

    def test_the_link_becomes_invalid_once_the_password_changes(self):
        self.user.set_password('yeni-parola-1')
        self.user.save(session=self.session)

        res = self.client.get(self.url(self.uidb64, self.token))

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': 'invalid_token_or_expired'})


class ResetPasswordConfirmTests(TestCase):
    """``POST /api/user/reset-password/confirm/``."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            email='onayla@pythontr.com',
            password='123qwe',
            is_active=True,
        )
        self.payload = {
            'password': 'yeni-parola-1',
            'confirm_password': 'yeni-parola-1',
            'token': default_token_generator.make_token(self.user),
            'uidb64': uid_of(self.user),
        }

    def test_a_good_token_replaces_the_password(self):
        res = self.client.post(RESET_CONFIRM_URL, self.payload)

        self.assertEqual(res.status_code, status.HTTP_200_OK)
        self.assertEqual(
            res.data, {'message': 'password_reset_success_message'})
        self.session.refresh(self.user)
        self.assertTrue(self.user.check_password('yeni-parola-1'))
        self.assertFalse(self.user.check_password('123qwe'))

    def test_a_uid_that_decodes_to_nobody_is_an_invalid_link(self):
        payload = dict(
            self.payload, uidb64=urlsafe_base64_encode(b'99999999'))

        res = self.client.post(RESET_CONFIRM_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': ['invalid_link']})

    def test_a_uid_that_is_not_base64_is_an_invalid_link(self):
        payload = dict(self.payload, uidb64='***')

        res = self.client.post(RESET_CONFIRM_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': ['invalid_link']})

    def test_a_forged_token_is_refused_with_its_own_message(self):
        payload = dict(self.payload, token='sahte-imza')

        res = self.client.post(RESET_CONFIRM_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(res.data, {'error': ['invalid_link_or_expired']})

    def test_the_two_passwords_have_to_agree(self):
        payload = dict(self.payload, confirm_password='baska-parola')

        res = self.client.post(RESET_CONFIRM_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data, {'confirm_password': ['passwords_do_not_match']})

    def test_a_short_password_is_rejected_before_the_token_is_read(self):
        payload = dict(
            self.payload, password='kisa', confirm_password='kisa',
            token='sahte-imza')

        res = self.client.post(RESET_CONFIRM_URL, payload)

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            res.data,
            {'password': [
                'Bu alanın en az 8 karakter barındırdığından emin olun.']})

    def test_every_field_is_required(self):
        res = self.client.post(RESET_CONFIRM_URL, {})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertEqual(
            list(res.data), ['password', 'confirm_password', 'token',
                             'uidb64'])
        self.assertEqual(res.data['token'], ['Bu alan zorunlu.'])

    def test_the_confirm_path_refuses_a_delete(self):
        res = self.client.delete(RESET_CONFIRM_URL)

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"DELETE" metoduna izin verilmiyor.'})
