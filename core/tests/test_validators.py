"""The four password validators ``AUTH_PASSWORD_VALIDATORS`` names.

Nothing in the request path calls them -- the baseline never wired them
into the create or update views and the port preserves that -- so these
tests drive the classes directly.  What they pin down is the accept /
reject decision and the ``code`` each rejection carries, because those
codes are what a caller that did wire them up would branch on.
"""

from __future__ import annotations

from app import validators
from app.testing import TestCase, get_user_model


class UserAttributeSimilarityValidatorTests(TestCase):

    def setUp(self):
        self.validator = validators.UserAttributeSimilarityValidator()
        self.user = get_user_model().objects.create_user(
            email='huseyin@pythontr.com',
            password='123qwe',
            name='huseyin',
            username='ozdemir',
        )

    def test_an_unrelated_password_is_accepted(self):
        self.assertIsNone(
            self.validator.validate('mor-kaplumbaga-42', self.user))

    def test_a_password_equal_to_the_username_is_rejected(self):
        with self.assertRaises(validators.ValidationError) as caught:
            self.validator.validate('ozdemir', self.user)

        self.assertEqual(caught.exception.code, 'password_too_similar')
        self.assertEqual(
            caught.exception.message,
            'The password is too similar to the username.')

    def test_a_password_equal_to_the_name_is_rejected(self):
        with self.assertRaises(validators.ValidationError) as caught:
            self.validator.validate('HUSEYIN', self.user)

        self.assertEqual(caught.exception.code, 'password_too_similar')
        self.assertEqual(
            caught.exception.message,
            'The password is too similar to the name.')

    def test_a_word_out_of_the_email_is_rejected(self):
        with self.assertRaises(validators.ValidationError) as caught:
            self.validator.validate('pythontr', self.user)

        self.assertEqual(
            caught.exception.message,
            'The password is too similar to the email.')

    def test_a_blank_attribute_is_skipped(self):
        self.assertEqual(self.user.surname, '')

        self.assertIsNone(self.validator.validate('', self.user))

    def test_a_non_string_attribute_is_skipped(self):
        validator = validators.UserAttributeSimilarityValidator(
            user_attributes=('id',))

        self.assertIsNone(
            validator.validate(str(self.user.id), self.user))

    def test_without_a_user_nothing_is_compared(self):
        self.assertIsNone(self.validator.validate('ozdemir'))
        self.assertIsNone(self.validator.validate('ozdemir', None))


class MinimumLengthValidatorTests(TestCase):

    def setUp(self):
        self.validator = validators.MinimumLengthValidator()

    def test_the_default_minimum_is_eight_characters(self):
        self.assertEqual(self.validator.min_length, 8)
        self.assertIsNone(self.validator.validate('12345678'))

    def test_a_seven_character_password_is_rejected(self):
        with self.assertRaises(validators.ValidationError) as caught:
            self.validator.validate('1234567')

        self.assertEqual(caught.exception.code, 'password_too_short')
        self.assertEqual(
            caught.exception.message, 'This password is too short.')

    def test_the_minimum_is_configurable(self):
        validator = validators.MinimumLengthValidator(min_length=12)

        self.assertIsNone(validator.validate('123456789012'))
        with self.assertRaises(validators.ValidationError):
            validator.validate('12345678901')


class CommonPasswordValidatorTests(TestCase):

    def setUp(self):
        self.validator = validators.CommonPasswordValidator()

    def test_an_uncommon_password_is_accepted(self):
        self.assertIsNone(self.validator.validate('mor-kaplumbaga-42'))

    def test_a_listed_password_is_rejected(self):
        with self.assertRaises(validators.ValidationError) as caught:
            self.validator.validate('qwerty')

        self.assertEqual(caught.exception.code, 'password_too_common')
        self.assertEqual(
            caught.exception.message, 'This password is too common.')

    def test_case_and_surrounding_space_do_not_disguise_a_listed_password(
            self):
        with self.assertRaises(validators.ValidationError):
            self.validator.validate('  PassWord ')

    def test_the_list_is_configurable(self):
        validator = validators.CommonPasswordValidator(
            password_list=frozenset({'pythontr'}))

        self.assertIsNone(validator.validate('qwerty'))
        with self.assertRaises(validators.ValidationError):
            validator.validate('pythontr')


class NumericPasswordValidatorTests(TestCase):

    def setUp(self):
        self.validator = validators.NumericPasswordValidator()

    def test_a_password_with_a_letter_is_accepted(self):
        self.assertIsNone(self.validator.validate('1234567a'))

    def test_an_all_digit_password_is_rejected(self):
        with self.assertRaises(validators.ValidationError) as caught:
            self.validator.validate('12345678')

        self.assertEqual(
            caught.exception.code, 'password_entirely_numeric')
        self.assertEqual(
            caught.exception.message,
            'This password is entirely numeric.')


class ValidationErrorTests(TestCase):

    def test_the_message_is_carried_by_both_str_and_the_attribute(self):
        error = validators.ValidationError('cok kisa', code='too_short')

        self.assertEqual(str(error), 'cok kisa')
        self.assertEqual(error.message, 'cok kisa')
        self.assertEqual(error.code, 'too_short')

    def test_the_code_is_optional(self):
        error = validators.ValidationError('cok kisa')

        self.assertIsNone(error.code)
