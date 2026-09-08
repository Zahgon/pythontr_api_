"""Password hashing, auth tokens, uid encoding and reset tokens.

``app.security`` is the one module whose output has to stay byte
compatible with rows that are already in the database: a password
written before the port must keep verifying afterwards.  The seeded
hash below was produced by the original stack, so it is the anchor the
rest of the module is checked against.
"""

from __future__ import annotations

from typing import List

from app import security
from app.security import PasswordResetTokenGenerator
from app.testing import TestCase, get_user_model

#: Written by the baseline for the password ``probepass123``.
SEEDED_HASH = (
    'pbkdf2_sha256$600000$fixedsalt00000000000$'
    'atwH4Ti59RkdeEmmLzLOUAG1MlRArrElK6aoWBbQq7s='
)
SEEDED_PASSWORD = 'probepass123'


class PasswordHashingTests(TestCase):

    def test_make_password_round_trips_through_check_password(self):
        encoded = security.make_password('123qwe')

        self.assertTrue(encoded.startswith('pbkdf2_sha256$600000$'))
        self.assertTrue(security.check_password('123qwe', encoded))
        self.assertFalse(security.check_password('123qwd', encoded))

    def test_two_hashes_of_one_password_differ_by_salt(self):
        first = security.make_password('123qwe')
        second = security.make_password('123qwe')

        self.assertNotEqual(first, second)
        self.assertTrue(security.check_password('123qwe', first))
        self.assertTrue(security.check_password('123qwe', second))

    def test_seeded_hash_still_verifies(self):
        self.assertTrue(
            security.check_password(SEEDED_PASSWORD, SEEDED_HASH))
        self.assertFalse(
            security.check_password('probepass124', SEEDED_HASH))

    def test_seeded_hash_is_reproduced_from_its_own_salt(self):
        algorithm, iterations, salt_value, _digest = SEEDED_HASH.split('$', 3)

        rebuilt = security.make_password(
            SEEDED_PASSWORD, salt_value, int(iterations))

        self.assertEqual(algorithm, 'pbkdf2_sha256')
        self.assertEqual(rebuilt, SEEDED_HASH)

    def test_none_password_produces_an_unusable_placeholder(self):
        encoded = security.make_password(None)

        self.assertTrue(encoded.startswith('!'))
        self.assertEqual(len(encoded), 41)
        self.assertFalse(security.is_password_usable(encoded))
        self.assertFalse(security.check_password('', encoded))

    def test_is_password_usable_accepts_a_real_hash_and_none(self):
        self.assertTrue(security.is_password_usable(SEEDED_HASH))
        self.assertTrue(security.is_password_usable(None))

    def test_salt_may_not_carry_the_field_separator(self):
        with self.assertRaises(ValueError):
            security.make_password('123qwe', 'ba$d')

    def test_generated_salt_is_the_documented_width(self):
        value = security.salt()

        self.assertEqual(len(value), 22)
        self.assertNotIn('$', value)
        self.assertTrue(
            set(value) <= set(security.RANDOM_STRING_CHARS))

    def test_check_password_rejects_a_none_password(self):
        self.assertFalse(security.check_password(None, SEEDED_HASH))

    def test_check_password_rejects_malformed_encodings(self):
        self.assertFalse(security.check_password('123qwe', ''))
        self.assertFalse(security.check_password('123qwe', 'nodollars'))
        self.assertFalse(
            security.check_password('123qwe', 'md5$600000$salt$digest'))
        self.assertFalse(
            security.check_password(
                SEEDED_PASSWORD,
                'pbkdf2_sha256$many$fixedsalt00000000000$x='))

    def test_check_password_upgrades_a_stale_iteration_count(self):
        stale = security.make_password('123qwe', 'staticsalt', 1000)
        upgraded: List[str] = []

        correct = security.check_password(
            '123qwe', stale, setter=upgraded.append)

        self.assertTrue(correct)
        self.assertEqual(upgraded, ['123qwe'])

    def test_check_password_leaves_a_current_hash_alone(self):
        current = security.make_password('123qwe')
        upgraded: List[str] = []

        correct = security.check_password(
            '123qwe', current, setter=upgraded.append)

        self.assertTrue(correct)
        self.assertEqual(upgraded, [])


class TokenAndEncodingTests(TestCase):

    def test_generate_token_fills_the_stored_column_width(self):
        token = security.generate_token()

        self.assertEqual(len(token), 40)
        self.assertEqual(token, token.lower())
        self.assertTrue(set(token) <= set('0123456789abcdef'))
        self.assertNotEqual(token, security.generate_token())

    def test_urlsafe_base64_round_trips_without_padding(self):
        encoded = security.urlsafe_base64_encode(b'12345')

        self.assertNotIn('=', encoded)
        self.assertEqual(security.urlsafe_base64_decode(encoded), b'12345')

    def test_urlsafe_base64_encodes_a_primary_key_the_reset_link_carries(self):
        encoded = security.urlsafe_base64_encode(b'7')

        self.assertEqual(encoded, 'Nw')
        self.assertEqual(security.urlsafe_base64_decode('Nw'), b'7')

    def test_base36_round_trips_across_the_digit_boundary(self):
        for value in (0, 35, 36, 1234567, 1700000000):
            self.assertEqual(
                security.base36_to_int(security.int_to_base36(value)), value)

    def test_int_to_base36_uses_lowercase_alphanumerics(self):
        self.assertEqual(security.int_to_base36(0), '0')
        self.assertEqual(security.int_to_base36(35), 'z')
        self.assertEqual(security.int_to_base36(36), '10')

    def test_int_to_base36_refuses_a_negative_input(self):
        with self.assertRaises(ValueError):
            security.int_to_base36(-1)

    def test_base36_to_int_refuses_an_oversized_input(self):
        with self.assertRaises(ValueError):
            security.base36_to_int('z' * 14)

    def test_constant_time_compare_matches_across_str_and_bytes(self):
        self.assertTrue(security.constant_time_compare('abc', 'abc'))
        self.assertTrue(security.constant_time_compare('abc', b'abc'))
        self.assertTrue(security.constant_time_compare(b'abc', 'abc'))
        self.assertFalse(security.constant_time_compare('abc', 'abd'))

    def test_force_bytes_passes_bytes_through_and_encodes_the_rest(self):
        self.assertEqual(security.force_bytes(b'x'), b'x')
        self.assertEqual(security.force_bytes(12), b'12')
        self.assertEqual(security.force_bytes('ş'), 'ş'.encode('utf-8'))

    def test_salted_hmac_is_deterministic_and_keyed_by_salt_and_secret(self):
        base = security.salted_hmac('salt', 'value', 'secret').hexdigest()

        self.assertEqual(
            security.salted_hmac(b'salt', b'value', b'secret').hexdigest(),
            base)
        self.assertNotEqual(
            security.salted_hmac('other', 'value', 'secret').hexdigest(),
            base)
        self.assertNotEqual(
            security.salted_hmac('salt', 'value', 'other').hexdigest(),
            base)


class PasswordResetTokenTests(TestCase):

    def setUp(self):
        self.generator = PasswordResetTokenGenerator()
        self.user = get_user_model().objects.create_user(
            email='reset@pythontr.com',
            password='123qwe',
        )

    def test_a_fresh_token_checks_out_for_its_own_user(self):
        token = self.generator.make_token(self.user)

        self.assertIn('-', token)
        self.assertTrue(self.generator.check_token(self.user, token))

    def test_a_token_does_not_check_out_for_another_user(self):
        other = get_user_model().objects.create_user(
            email='other-reset@pythontr.com',
            password='123qwe',
        )
        token = self.generator.make_token(self.user)

        self.assertTrue(self.generator.check_token(self.user, token))
        self.assertFalse(self.generator.check_token(other, token))

    def test_changing_the_password_invalidates_an_outstanding_token(self):
        token = self.generator.make_token(self.user)

        self.user.set_password('yenisifre')

        self.assertFalse(self.generator.check_token(self.user, token))

    def test_a_token_older_than_the_timeout_is_rejected(self):
        issued_at = (
            self.generator._num_seconds(self.generator._now())
            - security.PASSWORD_RESET_TIMEOUT - 1
        )
        token = self.generator._make_token_with_timestamp(
            self.user, issued_at)

        self.assertFalse(self.generator.check_token(self.user, token))

    def test_a_token_inside_the_timeout_is_accepted(self):
        issued_at = (
            self.generator._num_seconds(self.generator._now())
            - security.PASSWORD_RESET_TIMEOUT + 60
        )
        token = self.generator._make_token_with_timestamp(
            self.user, issued_at)

        self.assertTrue(self.generator.check_token(self.user, token))

    def test_check_token_rejects_missing_and_malformed_tokens(self):
        self.assertFalse(self.generator.check_token(self.user, None))
        self.assertFalse(self.generator.check_token(self.user, ''))
        self.assertFalse(self.generator.check_token(None, 'abc-def'))
        self.assertFalse(self.generator.check_token(self.user, 'nodash'))
        self.assertFalse(self.generator.check_token(self.user, 'a-b-c'))
        self.assertFalse(self.generator.check_token(self.user, '!!-abcdef'))

    def test_a_tampered_hash_half_is_rejected(self):
        timestamp, _hash = self.generator.make_token(self.user).split('-')

        forged = '%s-%s' % (timestamp, 'f' * 32)

        self.assertFalse(self.generator.check_token(self.user, forged))

    def test_a_generator_with_another_secret_rejects_the_token(self):
        token = self.generator.make_token(self.user)

        other = PasswordResetTokenGenerator(secret='baska-bir-anahtar')

        self.assertFalse(other.check_token(self.user, token))

    def test_the_timestamp_half_is_the_base36_issue_time(self):
        token = self.generator.make_token(self.user)
        timestamp, _hash = token.split('-')

        issued_at = security.base36_to_int(timestamp)
        now = self.generator._num_seconds(self.generator._now())

        self.assertLessEqual(issued_at, now)
        self.assertGreaterEqual(issued_at, now - 60)

    def test_the_default_generator_uses_the_project_secret(self):
        from app import settings

        self.assertEqual(
            security.default_token_generator.secret, settings.SECRET_KEY)
        self.assertTrue(
            security.default_token_generator.check_token(
                self.user,
                security.default_token_generator.make_token(self.user)))
