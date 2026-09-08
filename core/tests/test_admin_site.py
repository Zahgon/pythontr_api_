"""The server-rendered administration site at ``/admin/``.

``core/tests/test_admin.py`` checks that three signed-in pages answer at
all.  What is not covered anywhere is the part of the site that decides
*whether* a caller may see them: the redirect chain, the login form and
its masked CSRF pair, the credential check, and the write half of the
changelist and change form.
"""

from __future__ import annotations

import re

from app.admin_site import CSRF_COOKIE, SESSION_COOKIE, _unmask_csrf_token
from app.testing import Client, TestCase, get_user_model

ADMIN_URL = '/admin/'
LOGIN_URL = '/admin/login/'
LOGOUT_URL = '/admin/logout/'
USER_CHANGELIST_URL = '/admin/core/user/'
USER_ADD_URL = '/admin/core/user/add/'

HTML_TYPE = 'text/html; charset=utf-8'

_CSRF_FIELD_RE = re.compile(
    r'name="csrfmiddlewaretoken" value="([A-Za-z0-9]+)"')


class AnonymousAdminSiteTests(TestCase):

    def setUp(self):
        self.client = Client()

    def test_the_index_sends_an_anonymous_caller_to_the_login_form(self):
        res = self.client.get(ADMIN_URL)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], '/admin/login/?next=/admin/')
        self.assertEqual(res['Content-Type'], HTML_TYPE)

    def test_a_changelist_remembers_where_the_caller_was_going(self):
        res = self.client.get(USER_CHANGELIST_URL)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(
            res['Location'], '/admin/login/?next=/admin/core/user/')

    def test_a_change_form_remembers_where_the_caller_was_going(self):
        res = self.client.get('/admin/core/user/7/change/')

        self.assertEqual(res.status_code, 302)
        self.assertEqual(
            res['Location'], '/admin/login/?next=/admin/core/user/7/change/')

    def test_the_add_form_remembers_where_the_caller_was_going(self):
        res = self.client.get(USER_ADD_URL)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(
            res['Location'], '/admin/login/?next=/admin/core/user/add/')

    def test_admin_pages_are_never_cached(self):
        res = self.client.get(LOGIN_URL)

        self.assertEqual(
            res['Cache-Control'],
            'max-age=0, no-cache, no-store, must-revalidate, private')
        self.assertIn('Cookie', res['Vary'])


class LoginFormTests(TestCase):

    def setUp(self):
        self.client = Client()

    def test_the_form_renders_as_html(self):
        res = self.client.get(LOGIN_URL)

        self.assertEqual(res.status_code, 200)
        self.assertEqual(res['Content-Type'], HTML_TYPE)
        self.assertContains(res, 'id="container"')
        self.assertContains(res, 'id="login-form"')
        self.assertContains(res, 'id="id_username"')

    def test_the_form_carries_a_masked_csrf_pair(self):
        res = self.client.get(LOGIN_URL)

        field = _CSRF_FIELD_RE.search(res.text).group(1)
        secret = self.client.cookies[CSRF_COOKIE]
        self.assertEqual(len(field), 64)
        self.assertEqual(len(secret), 32)
        self.assertNotEqual(field[32:], secret)
        self.assertEqual(_unmask_csrf_token(field), secret)

    def test_two_renders_mask_the_same_secret_differently(self):
        first = _CSRF_FIELD_RE.search(self.client.get(LOGIN_URL).text)
        second = _CSRF_FIELD_RE.search(self.client.get(LOGIN_URL).text)

        secret = self.client.cookies[CSRF_COOKIE]
        self.assertNotEqual(first.group(1), second.group(1))
        self.assertEqual(_unmask_csrf_token(first.group(1)), secret)
        self.assertEqual(_unmask_csrf_token(second.group(1)), secret)

    def test_the_form_carries_the_destination_it_was_asked_for(self):
        res = self.client.get(LOGIN_URL + '?next=/admin/core/user/')

        self.assertContains(
            res, '<input type="hidden" name="next" '
                 'value="/admin/core/user/">')

    def test_an_unmask_of_the_wrong_width_is_returned_unchanged(self):
        self.assertEqual(_unmask_csrf_token('kisa'), 'kisa')


class LoginSubmissionTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.staff = get_user_model().objects.create_superuser(
            email='yonetici@pythontr.com', password='123qwe')
        self.member = get_user_model().objects.create_user(
            email='uye@pythontr.com', password='123qwe', is_active=True)

    def submit(self, email, password, next_url='/admin/'):
        page = self.client.get(LOGIN_URL)
        token = _CSRF_FIELD_RE.search(page.text).group(1)
        return self.client.post(LOGIN_URL, {
            'username': email,
            'password': password,
            'next': next_url,
            'csrfmiddlewaretoken': token,
        })

    def test_a_staff_account_is_redirected_to_the_destination(self):
        res = self.submit('yonetici@pythontr.com', '123qwe')

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], '/admin/')

    def test_a_signed_in_caller_is_issued_a_session_cookie(self):
        res = self.submit('yonetici@pythontr.com', '123qwe')

        cookies = [
            value for name, value in res.headers.multi_items()
            if name.lower() == 'set-cookie'
            and value.startswith(SESSION_COOKIE + '=')
        ]
        self.assertEqual(len(cookies), 1)
        self.assertIn('HttpOnly', cookies[0])
        self.assertIn('Max-Age=1209600', cookies[0])

    def test_the_destination_of_the_form_is_honoured(self):
        res = self.submit(
            'yonetici@pythontr.com', '123qwe', next_url='/admin/core/user/')

        self.assertEqual(res['Location'], '/admin/core/user/')

    def test_a_wrong_password_re_renders_the_form_with_a_notice(self):
        res = self.submit('yonetici@pythontr.com', 'yanlis')

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'class="errornote"')
        self.assertContains(res, 'doğru Email ve parola giriniz')
        self.assertNotIn(SESSION_COOKIE, self.client.cookies)

    def test_an_unknown_address_re_renders_the_form_with_a_notice(self):
        res = self.submit('yok@pythontr.com', '123qwe')

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'class="errornote"')

    def test_an_account_without_staff_rights_is_turned_away(self):
        res = self.submit('uye@pythontr.com', '123qwe')

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'class="errornote"')
        self.assertNotIn(SESSION_COOKIE, self.client.cookies)

    def test_a_submission_without_a_csrf_cookie_is_refused(self):
        res = self.client.post(LOGIN_URL, {
            'username': 'yonetici@pythontr.com',
            'password': '123qwe',
            'csrfmiddlewaretoken': 'a' * 64,
        })

        self.assertEqual(res.status_code, 403)
        self.assertEqual(
            res.text, 'CSRF doğrulaması başarısız oldu. İstek iptal edildi.')

    def test_a_submission_whose_token_does_not_match_is_refused(self):
        self.client.get(LOGIN_URL)

        res = self.client.post(LOGIN_URL, {
            'username': 'yonetici@pythontr.com',
            'password': '123qwe',
            'csrfmiddlewaretoken': 'z' * 64,
        })

        self.assertEqual(res.status_code, 403)


class LogoutTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.staff = get_user_model().objects.create_superuser(
            email='yonetici@pythontr.com', password='123qwe')
        self.client.force_login(self.staff)

    def test_logging_out_returns_to_the_login_form(self):
        res = self.client.get(LOGOUT_URL)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], '/admin/login/?next=/admin/')

    def test_logging_out_expires_the_session_cookie(self):
        res = self.client.get(LOGOUT_URL)

        cleared = [
            value for name, value in res.headers.multi_items()
            if name.lower() == 'set-cookie'
            and value.startswith(SESSION_COOKIE + '=')
        ]
        self.assertEqual(len(cleared), 1)
        self.assertIn('Max-Age=0', cleared[0])
        self.assertEqual(cleared[0].split(';')[0], SESSION_COOKIE + '=')

    def test_the_index_redirects_again_once_the_cookie_is_gone(self):
        self.client.get(LOGOUT_URL)
        self.client.logout()

        res = self.client.get(ADMIN_URL)

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], '/admin/login/?next=/admin/')


class SignedInAdminSiteTests(TestCase):

    def setUp(self):
        self.client = Client()
        self.staff = get_user_model().objects.create_superuser(
            email='yonetici@pythontr.com', password='123qwe')
        self.client.force_login(self.staff)
        self.member = get_user_model().objects.create_user(
            email='ayse@pythontr.com',
            password='123qwe',
            name='Ayse',
            surname='Yilmaz',
            is_active=True,
        )

    # -- index ----------------------------------------------------------

    def test_the_index_names_the_signed_in_account(self):
        res = self.client.get(ADMIN_URL)

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="user-tools"')
        self.assertContains(res, 'yonetici@pythontr.com')
        self.assertContains(res, '<title>Site yönetimi |')

    def test_the_index_lists_every_registered_model(self):
        res = self.client.get(ADMIN_URL)

        for label in ('Kullanıcılar', 'Kategoriler', 'Makaleler',
                      'Yorumlar', 'Mesajlar', 'Slaytlar',
                      'Sayfa ziyaretleri'):
            self.assertContains(res, label)

    def test_the_index_offers_no_add_link_for_page_visits(self):
        res = self.client.get(ADMIN_URL)

        self.assertContains(res, 'href="/admin/core/user/add/"')
        self.assertNotContains(res, 'href="/admin/core/pagevisit/add/"')

    # -- changelist -----------------------------------------------------

    def email_cell(self, email):
        return '<td class="field-email">%s</td>' % email

    def test_the_changelist_lists_the_rows_and_counts_them(self):
        res = self.client.get(USER_CHANGELIST_URL)

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="result_list"')
        self.assertContains(res, self.email_cell('yonetici@pythontr.com'))
        self.assertContains(res, self.email_cell('ayse@pythontr.com'))
        self.assertContains(res, '2 sonuç')

    def test_a_changelist_row_links_to_its_change_form(self):
        res = self.client.get(USER_CHANGELIST_URL)

        self.assertContains(
            res,
            'href="/admin/core/user/%d/change/"' % self.member.id)

    def test_the_search_narrows_the_changelist(self):
        res = self.client.get(USER_CHANGELIST_URL + '?q=Yilmaz')

        self.assertContains(res, self.email_cell('ayse@pythontr.com'))
        self.assertNotContains(
            res, self.email_cell('yonetici@pythontr.com'))
        self.assertContains(res, '1 sonuç')

    def test_a_search_that_matches_nothing_reports_no_rows(self):
        res = self.client.get(USER_CHANGELIST_URL + '?q=zzzz')

        self.assertContains(res, '0 sonuç')
        self.assertNotContains(res, self.email_cell('ayse@pythontr.com'))

    def test_a_filter_narrows_the_changelist_and_marks_it(self):
        res = self.client.get(USER_CHANGELIST_URL + '?is_staff=True')

        self.assertContains(res, 'class="module filtered"')
        self.assertContains(res, self.email_cell('yonetici@pythontr.com'))
        self.assertNotContains(res, self.email_cell('ayse@pythontr.com'))

    def test_the_filter_sidebar_offers_both_values(self):
        res = self.client.get(USER_CHANGELIST_URL)

        self.assertContains(res, 'id="changelist-filter"')
        self.assertContains(res, 'href="?is_active=True"')
        self.assertContains(res, 'href="?is_active=False"')

    def test_an_unregistered_model_is_not_found(self):
        res = self.client.get('/admin/core/yokboyle/')

        self.assertEqual(res.status_code, 404)
        self.assertIn('Page not found', res.text)

    def test_an_unregistered_app_is_not_found(self):
        res = self.client.get('/admin/baskaapp/user/')

        self.assertEqual(res.status_code, 404)

    # -- change form ----------------------------------------------------

    def change_url(self, row):
        return '/admin/core/user/%d/change/' % row.id

    def test_the_change_form_is_filled_from_the_row(self):
        res = self.client.get(self.change_url(self.member))

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'id="user_form"')
        self.assertContains(
            res, 'name="email" id="id_email" value="ayse@pythontr.com"')
        self.assertContains(res, 'name="name" id="id_name" value="Ayse"')

    def test_a_boolean_column_is_rendered_as_a_checked_box(self):
        res = self.client.get(self.change_url(self.member))

        self.assertContains(
            res,
            '<input type="checkbox" name="is_active" id="id_is_active"'
            ' checked>')
        self.assertContains(
            res,
            '<input type="checkbox" name="is_staff" id="id_is_staff">')

    def test_a_missing_row_has_no_change_form(self):
        res = self.client.get('/admin/core/user/9999999/change/')

        self.assertEqual(res.status_code, 404)

    def test_an_unregistered_model_has_no_change_form(self):
        res = self.client.get('/admin/core/yokboyle/1/change/')

        self.assertEqual(res.status_code, 404)

    def test_saving_the_change_form_writes_the_edit_back(self):
        res = self.client.post(self.change_url(self.member), {
            'email': 'ayse@pythontr.com',
            'username': 'ayse',
            'name': 'Ayse Nur',
            'surname': 'Yilmaz',
            'is_active': 'on',
        })

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], USER_CHANGELIST_URL)
        self.session.refresh(self.member)
        self.assertEqual(self.member.name, 'Ayse Nur')

    def test_a_checkbox_left_out_of_the_submission_is_cleared(self):
        self.client.post(self.change_url(self.member), {
            'email': 'ayse@pythontr.com',
            'username': 'ayse',
            'name': 'Ayse',
        })

        self.session.refresh(self.member)
        self.assertFalse(self.member.is_active)

    def test_a_field_left_out_of_the_submission_keeps_its_value(self):
        self.client.post(self.change_url(self.member), {
            'email': 'ayse@pythontr.com',
            'username': 'ayse',
            'is_active': 'on',
        })

        self.session.refresh(self.member)
        self.assertEqual(self.member.name, 'Ayse')

    def test_saving_an_unregistered_model_is_not_found(self):
        res = self.client.post('/admin/core/yokboyle/1/change/', {})

        self.assertEqual(res.status_code, 404)

    def test_saving_a_missing_row_is_not_found(self):
        res = self.client.post('/admin/core/user/9999999/change/', {})

        self.assertEqual(res.status_code, 404)

    # -- add form -------------------------------------------------------

    def test_the_add_form_is_empty(self):
        res = self.client.get(USER_ADD_URL)

        self.assertEqual(res.status_code, 200)
        self.assertContains(res, 'name="email" id="id_email" value=""')
        self.assertContains(
            res,
            '<input type="checkbox" name="is_active" id="id_is_active">')

    def test_the_add_form_creates_the_row(self):
        res = self.client.post(USER_ADD_URL, {
            'email': 'yeni@pythontr.com',
            'username': 'yeni',
            'name': 'Yeni',
            'is_active': 'on',
        })

        self.assertEqual(res.status_code, 302)
        self.assertEqual(res['Location'], USER_CHANGELIST_URL)
        created = get_user_model().objects.get(email='yeni@pythontr.com')
        self.assertEqual(created.name, 'Yeni')
        self.assertTrue(created.is_active)
        self.assertEqual(created.slug, 'yeni')

    def test_a_model_that_forbids_adding_has_no_add_form(self):
        res = self.client.get('/admin/core/pagevisit/add/')

        self.assertEqual(res.status_code, 404)

    def test_a_model_that_forbids_adding_refuses_the_submission(self):
        res = self.client.post('/admin/core/pagevisit/add/', {
            'path': '/makale/1',
        })

        self.assertEqual(res.status_code, 404)

    def test_an_unregistered_model_has_no_add_form(self):
        res = self.client.get('/admin/core/yokboyle/add/')

        self.assertEqual(res.status_code, 404)
