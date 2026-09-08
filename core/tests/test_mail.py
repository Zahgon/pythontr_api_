"""Outgoing mail: the message, the dispatcher and the four backends.

The suite selects the in-memory backend, so the console and SMTP paths
are never exercised by a request.  They are driven directly here --
``smtplib.SMTP`` is patched throughout, so nothing dials out.
"""

from __future__ import annotations

import io
import smtplib
import ssl
from email import message_from_string
from typing import List
from unittest.mock import MagicMock, patch

from app import mail, settings
from app.custom_email_backend import CustomEmailBackend
from app.mail import EmailMessage, get_connection, send_mail
from app.mail.backends import console, locmem, smtp
from app.mail.backends.base import BaseEmailBackend
from app.testing import TestCase

LOCMEM_PATH = 'app.mail.backends.locmem.EmailBackend'
CONSOLE_PATH = 'app.mail.backends.console.EmailBackend'
SMTP_PATH = 'app.mail.backends.smtp.EmailBackend'


class _ConsoleMessage:
    """A message shaped the way the console backend reads one.

    ``EmailMessage.recipients`` is a property while the console backend
    calls it, so the two do not fit together; the mismatch is asserted
    below and this stand-in supplies the shape the backend expects.
    """

    def __init__(self, subject, body, from_email, to):
        self.subject = subject
        self.body = body
        self.from_email = from_email
        self.to = list(to)

    def recipients(self) -> List[str]:
        return list(self.to)


class EmailMessageTests(TestCase):

    def test_recipients_is_a_copy_of_the_to_list(self):
        message = EmailMessage(to=['a@pythontr.com', 'b@pythontr.com'])

        recipients = message.recipients

        self.assertEqual(recipients, ['a@pythontr.com', 'b@pythontr.com'])
        recipients.append('c@pythontr.com')
        self.assertEqual(message.to, ['a@pythontr.com', 'b@pythontr.com'])

    def test_an_omitted_sender_falls_back_to_the_configured_one(self):
        message = EmailMessage(subject='Merhaba')

        self.assertEqual(message.from_email, settings.DEFAULT_FROM_EMAIL)
        self.assertEqual(message.to, [])
        self.assertEqual(message.body, '')
        self.assertIsNone(message.connection)

    def test_send_uses_the_connection_it_was_built_with(self):
        connection = MagicMock()
        connection.send_messages.return_value = 1
        message = EmailMessage(
            subject='Merhaba', to=['a@pythontr.com'], connection=connection)

        sent = message.send()

        self.assertEqual(sent, 1)
        connection.send_messages.assert_called_once_with([message])


class GetConnectionTests(TestCase):

    def test_the_configured_backend_is_the_in_memory_one(self):
        self.assertEqual(settings.EMAIL_BACKEND, LOCMEM_PATH)
        self.assertIsInstance(get_connection(), locmem.EmailBackend)

    def test_a_dotted_path_selects_another_backend(self):
        connection = get_connection(CONSOLE_PATH)

        self.assertIsInstance(connection, console.EmailBackend)
        self.assertFalse(connection.fail_silently)

    def test_keyword_arguments_reach_the_backend(self):
        stream = io.StringIO()

        connection = get_connection(
            CONSOLE_PATH, fail_silently=True, stream=stream)

        self.assertIs(connection.stream, stream)
        self.assertTrue(connection.fail_silently)

    def test_an_unknown_class_in_a_known_module_is_an_error(self):
        with self.assertRaises(AttributeError):
            get_connection('app.mail.backends.locmem.NoSuchBackend')


class LocmemBackendTests(TestCase):

    def setUp(self):
        self.saved = list(mail.outbox)
        del mail.outbox[:]
        self.addCleanup(self._restore)

    def _restore(self):
        mail.outbox[:] = self.saved

    def test_send_mail_reports_one_delivery_and_files_the_message(self):
        sent = send_mail(
            'Merhaba',
            'govde',
            'no-reply@pythontr.com',
            ['a@pythontr.com'],
        )

        self.assertEqual(sent, 1)
        self.assertEqual(len(mail.outbox), 1)
        message = mail.outbox[0]
        self.assertEqual(message.subject, 'Merhaba')
        self.assertEqual(message.body, 'govde')
        self.assertEqual(message.from_email, 'no-reply@pythontr.com')
        self.assertEqual(message.recipients, ['a@pythontr.com'])

    def test_send_mail_honours_an_explicit_connection(self):
        connection = get_connection(LOCMEM_PATH)

        sent = send_mail(
            'Ikinci', 'govde', 'no-reply@pythontr.com',
            ['b@pythontr.com'], connection=connection)

        self.assertEqual(sent, 1)
        self.assertEqual(mail.outbox[-1].subject, 'Ikinci')

    def test_every_message_of_a_batch_is_filed(self):
        backend = locmem.EmailBackend()
        messages = [
            EmailMessage(subject='bir', to=['a@pythontr.com']),
            EmailMessage(subject='iki', to=['b@pythontr.com']),
        ]

        sent = backend.send_messages(messages)

        self.assertEqual(sent, 2)
        self.assertEqual([m.subject for m in mail.outbox], ['bir', 'iki'])

    def test_an_empty_batch_files_nothing(self):
        self.assertEqual(locmem.EmailBackend().send_messages([]), 0)
        self.assertEqual(mail.outbox, [])


class ConsoleBackendTests(TestCase):

    def setUp(self):
        self.stream = io.StringIO()
        self.backend = console.EmailBackend(stream=self.stream)

    def test_a_message_is_written_as_headers_a_body_and_a_rule(self):
        message = _ConsoleMessage(
            'Merhaba', 'govde', 'no-reply@pythontr.com',
            ['a@pythontr.com', 'b@pythontr.com'])

        sent = self.backend.send_messages([message])

        self.assertEqual(sent, 1)
        self.assertEqual(
            self.stream.getvalue(),
            'Subject: Merhaba\n'
            'From: no-reply@pythontr.com\n'
            'To: a@pythontr.com, b@pythontr.com\n'
            '\n'
            'govde\n'
            + '-' * 79 + '\n',
        )

    def test_each_message_of_a_batch_gets_its_own_block(self):
        messages = [
            _ConsoleMessage('bir', 'a', 'no-reply@pythontr.com',
                            ['a@pythontr.com']),
            _ConsoleMessage('iki', 'b', 'no-reply@pythontr.com',
                            ['b@pythontr.com']),
        ]

        sent = self.backend.send_messages(messages)
        body = self.stream.getvalue()

        self.assertEqual(sent, 2)
        self.assertEqual(body.count('-' * 79), 2)
        self.assertIn('Subject: bir', body)
        self.assertIn('Subject: iki', body)

    def test_an_empty_batch_writes_nothing(self):
        self.assertEqual(self.backend.send_messages([]), 0)
        self.assertEqual(self.stream.getvalue(), '')

    def test_the_default_stream_is_standard_output(self):
        import sys

        self.assertIs(console.EmailBackend().stream, sys.stdout)

    def test_the_project_message_type_does_not_fit_this_backend(self):
        message = EmailMessage(
            subject='Merhaba', body='govde', to=['a@pythontr.com'])

        with self.assertRaises(TypeError):
            self.backend.send_messages([message])

    def test_fail_silently_swallows_the_write_failure(self):
        backend = console.EmailBackend(
            stream=self.stream, fail_silently=True)
        message = EmailMessage(
            subject='Merhaba', body='govde', to=['a@pythontr.com'])

        self.assertEqual(backend.send_messages([message]), 0)


class BaseBackendTests(TestCase):

    def test_the_interface_reports_no_connection_and_no_delivery(self):
        backend = BaseEmailBackend()

        self.assertFalse(backend.fail_silently)
        self.assertFalse(backend.open())
        self.assertIsNone(backend.close())
        self.assertEqual(backend.send_messages([EmailMessage()]), 0)

    def test_the_context_manager_yields_the_backend_itself(self):
        backend = BaseEmailBackend(fail_silently=True)

        with backend as entered:
            self.assertIs(entered, backend)

        self.assertTrue(backend.fail_silently)


class SmtpBackendTests(TestCase):

    def setUp(self):
        self.patcher = patch('smtplib.SMTP')
        self.smtp = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.connection = self.smtp.return_value

    def message(self, to=('a@pythontr.com',)):
        return EmailMessage(
            subject='Merhaba',
            body='govde',
            from_email='no-reply@pythontr.com',
            to=list(to),
        )

    def test_the_defaults_come_from_the_settings_module(self):
        backend = smtp.EmailBackend()

        self.assertEqual(backend.host, settings.EMAIL_HOST)
        self.assertEqual(backend.port, settings.EMAIL_PORT)
        self.assertEqual(backend.username, settings.EMAIL_HOST_USER)
        self.assertEqual(backend.password, settings.EMAIL_HOST_PASSWORD)
        self.assertEqual(backend.use_tls, settings.EMAIL_USE_TLS)
        self.assertIsNone(backend.connection)

    def test_open_dials_the_configured_host_once(self):
        # Pinned, not defaulted: EMAIL_USE_TLS / EMAIL_HOST_USER come from
        # os.environ at import time, so an ambient value would make open()
        # call starttls or login and fail the assertions below for an
        # unrelated reason.  Defaulting is covered by the test above.
        backend = smtp.EmailBackend(
            host='mail.pythontr.com', port=587, username='', password='',
            use_tls=False)

        self.assertTrue(backend.open())
        self.assertFalse(backend.open())
        self.smtp.assert_called_once_with('mail.pythontr.com', 587)
        self.connection.starttls.assert_not_called()
        self.connection.login.assert_not_called()

    def test_open_starts_tls_and_logs_in_when_asked_to(self):
        backend = smtp.EmailBackend(
            host='mail.pythontr.com', port=587, username='u',
            password='p', use_tls=True)

        self.assertTrue(backend.open())
        self.connection.starttls.assert_called_once_with()
        self.connection.login.assert_called_once_with('u', 'p')

    def test_a_refused_connection_propagates_by_default(self):
        self.smtp.side_effect = OSError('connection refused')
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        with self.assertRaises(OSError):
            backend.open()

    def test_a_refused_connection_is_swallowed_when_asked(self):
        self.smtp.side_effect = smtplib.SMTPException('nope')
        backend = smtp.EmailBackend(
            host='mail.pythontr.com', fail_silently=True)

        self.assertFalse(backend.open())
        self.assertIsNone(backend.connection)
        self.assertEqual(backend.send_messages([self.message()]), 0)

    def test_send_messages_delivers_and_closes(self):
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        sent = backend.send_messages([self.message()])

        self.assertEqual(sent, 1)
        self.connection.quit.assert_called_once_with()
        self.assertIsNone(backend.connection)

    def test_the_delivered_document_carries_the_message(self):
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        backend.send_messages(
            [self.message(to=('a@pythontr.com', 'b@pythontr.com'))])

        sender, recipients, document = self.connection.sendmail.call_args[0]
        parsed = message_from_string(document)
        self.assertEqual(sender, 'no-reply@pythontr.com')
        self.assertEqual(recipients, ['a@pythontr.com', 'b@pythontr.com'])
        self.assertEqual(parsed['Subject'], 'Merhaba')
        self.assertEqual(parsed['From'], 'no-reply@pythontr.com')
        self.assertEqual(parsed['To'], 'a@pythontr.com, b@pythontr.com')
        self.assertEqual(
            parsed.get_payload(decode=True).decode('utf-8'), 'govde')

    def test_an_empty_batch_never_opens_a_connection(self):
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        self.assertEqual(backend.send_messages([]), 0)
        self.smtp.assert_not_called()

    def test_a_message_without_recipients_is_not_delivered(self):
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        sent = backend.send_messages([self.message(to=())])

        self.assertEqual(sent, 0)
        self.connection.sendmail.assert_not_called()
        self.connection.quit.assert_called_once_with()

    def test_a_rejected_message_propagates_by_default(self):
        self.connection.sendmail.side_effect = smtplib.SMTPException('550')
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        with self.assertRaises(smtplib.SMTPException):
            backend.send_messages([self.message()])

        self.connection.quit.assert_called_once_with()

    def test_a_rejected_message_is_counted_out_when_failing_silently(self):
        self.connection.sendmail.side_effect = smtplib.SMTPException('550')
        backend = smtp.EmailBackend(
            host='mail.pythontr.com', fail_silently=True)

        self.assertEqual(backend.send_messages([self.message()]), 0)

    def test_closing_without_a_connection_is_a_no_operation(self):
        backend = smtp.EmailBackend(host='mail.pythontr.com')

        self.assertIsNone(backend.close())
        self.connection.quit.assert_not_called()

    def test_a_failed_quit_propagates_but_still_drops_the_connection(self):
        self.connection.quit.side_effect = smtplib.SMTPException('bye')
        backend = smtp.EmailBackend(host='mail.pythontr.com')
        backend.open()

        with self.assertRaises(smtplib.SMTPException):
            backend.close()

        self.assertIsNone(backend.connection)

    def test_a_failed_quit_is_swallowed_when_failing_silently(self):
        self.connection.quit.side_effect = smtplib.SMTPException('bye')
        backend = smtp.EmailBackend(
            host='mail.pythontr.com', fail_silently=True)
        backend.open()

        self.assertIsNone(backend.close())
        self.assertIsNone(backend.connection)


class CustomEmailBackendTests(TestCase):

    def setUp(self):
        self.patcher = patch('smtplib.SMTP')
        self.smtp = self.patcher.start()
        self.addCleanup(self.patcher.stop)
        self.connection = self.smtp.return_value

    def test_open_negotiates_tls_without_verifying_the_certificate(self):
        backend = CustomEmailBackend(
            host='mail.pythontr.com', port=587, username='u',
            password='p', use_tls=True)

        self.assertTrue(backend.open())

        self.smtp.assert_called_once_with(
            'mail.pythontr.com', 587, timeout=10)
        context = self.connection.starttls.call_args[1]['context']
        self.assertIsInstance(context, ssl.SSLContext)
        self.assertFalse(context.check_hostname)
        self.assertIs(context.verify_mode, ssl.CERT_NONE)
        self.assertEqual(self.connection.ehlo.call_count, 2)
        self.connection.login.assert_called_once_with('u', 'p')

    def test_open_greets_once_and_leaves_tls_alone_when_it_is_off(self):
        backend = CustomEmailBackend(
            host='mail.pythontr.com', port=25, use_tls=False)

        self.assertTrue(backend.open())

        self.assertEqual(self.connection.ehlo.call_count, 1)
        self.connection.starttls.assert_not_called()

    def test_an_already_open_backend_is_not_reopened(self):
        backend = CustomEmailBackend(host='mail.pythontr.com')
        backend.open()

        self.assertFalse(backend.open())
        self.smtp.assert_called_once_with(
            'mail.pythontr.com', settings.EMAIL_PORT, timeout=10)

    def test_a_handshake_failure_propagates_by_default(self):
        self.connection.starttls.side_effect = ssl.SSLError('bad cert')
        backend = CustomEmailBackend(
            host='mail.pythontr.com', use_tls=True)

        with self.assertRaises(ssl.SSLError):
            backend.open()

    def test_a_handshake_failure_is_swallowed_when_failing_silently(self):
        self.connection.starttls.side_effect = ssl.SSLError('bad cert')
        backend = CustomEmailBackend(
            host='mail.pythontr.com', use_tls=True, fail_silently=True)

        self.assertFalse(backend.open())
