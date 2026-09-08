"""Edge behaviour of the wire, parsing and authentication layers.

These are the shapes a router never produces on its happy path: the empty
``204``, the four error envelopes, the page envelope's refusal of a page
that is not there, and the two authenticators' handling of credentials
that do not resolve.  Where a behaviour cannot be reached through a
request -- the body parser's media-type fork, for instance -- the layer is
driven with a real :class:`starlette.requests.Request` built from a scope.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, Optional
from unittest.mock import patch
from urllib.parse import quote

from pydantic import BaseModel, Field, ValidationError
from starlette import status
from starlette.requests import Request

from app import parsing, settings
from app.authentication import CookieTokenAuthentication, TokenAuthentication
from app.testing import APIClient, TestCase, get_user_model
from app.urls import reverse
from app.wire import (
    NotFound,
    UnsupportedMediaType,
    ValidationFailed,
    get_allow,
    iter_errors,
    page_size,
    paginate,
    set_allow,
)
from core.models import Article, Category, Token

CREATE_USER_URL = reverse('user:create')
RECIPE_ROOT_URL = '/api/recipe/'
ARTICLES_URL = reverse('recipe:article-list')


def build_request(
    path: str = '/api/recipe/articles/',
    method: str = 'GET',
    query: str = '',
    headers: Optional[Dict[str, str]] = None,
    body: bytes = b'',
) -> Request:
    """Build the request object the application layers actually receive."""
    raw = [
        (name.lower().encode('latin-1'), value.encode('latin-1'))
        for name, value in (headers or {}).items()
    ]

    async def receive() -> Dict[str, Any]:
        return {'type': 'http.request', 'body': body, 'more_body': False}

    return Request(
        {
            'type': 'http',
            'http_version': '1.1',
            'method': method,
            'scheme': 'http',
            'server': ('testserver', 80),
            'client': ('testclient', 50000),
            'root_path': '',
            'path': path,
            'raw_path': path.encode('utf-8'),
            'query_string': query.encode('utf-8'),
            'headers': raw,
        },
        receive,
    )


def run(coroutine):
    return asyncio.run(coroutine)


class EmptyResponseTests(TestCase):
    """A ``204`` describes nothing, so it declares no representation."""

    def setUp(self):
        self.client = APIClient()
        self.user = get_user_model().objects.create_user(
            'silen@pythontr.com', '123qwe')
        category = Category.objects.create(
            user=self.user, name='silme', short_name='silme')
        self.article = Article.objects.create(
            title='silinecek makale',
            title_h1='silinecek makale',
            description='aciklama',
            content='icerik',
            is_active=True,
        )
        self.article.categories.append(category)

    def test_a_deleted_article_answers_no_content_and_no_type(self):
        res = self.client.delete(
            reverse('recipe:article-detail', args=[self.article.id]))

        self.assertEqual(res.status_code, status.HTTP_204_NO_CONTENT)
        self.assertNotIn('Content-Type', res.headers)
        self.assertEqual(res.content, b'')
        self.assertIsNone(res.data)
        self.assertTrue(self.article.is_delete)

    def test_the_empty_response_still_advertises_the_path(self):
        res = self.client.delete(
            reverse('recipe:article-detail', args=[self.article.id]))

        self.assertEqual(
            res['Allow'], 'GET, PUT, PATCH, DELETE, HEAD, OPTIONS')
        self.assertEqual(res['Content-Language'], 'tr')


class ErrorEnvelopeTests(TestCase):

    def setUp(self):
        self.client = APIClient()

    def test_an_unsupported_method_names_the_method_it_refused(self):
        res = self.client.delete(RECIPE_ROOT_URL)

        self.assertEqual(
            res.status_code, status.HTTP_405_METHOD_NOT_ALLOWED)
        self.assertEqual(
            res.data, {'detail': '"DELETE" metoduna izin verilmiyor.'})
        self.assertEqual(res['Allow'], 'GET, HEAD, OPTIONS')

    def test_an_unsupported_media_type_names_the_type_it_refused(self):
        res = self.client.post(
            CREATE_USER_URL, {'email': 'a@pythontr.com'},
            content_type='application/xml')

        self.assertEqual(
            res.status_code, status.HTTP_415_UNSUPPORTED_MEDIA_TYPE)
        self.assertEqual(
            res.data,
            {'detail':
             'İstekte desteklenmeyen medya tipi: "application/xml".'})

    def test_a_body_that_is_not_the_json_it_claims_to_be_is_a_bad_request(
            self):
        res = self.client.post(
            CREATE_USER_URL, {'email': 'a@pythontr.com'},
            headers={'Content-Type': 'application/json'})

        self.assertEqual(res.status_code, status.HTTP_400_BAD_REQUEST)
        self.assertTrue(
            res.data['detail'].startswith('JSON parse error - '),
            res.data)


class ParseBodyTests(TestCase):

    def test_an_empty_json_document_reads_as_an_empty_mapping(self):
        request = build_request(
            method='POST', headers={'content-type': 'application/json'})

        self.assertEqual(run(parsing.parse_body(request)), {})

    def test_a_json_object_is_returned_as_it_arrived(self):
        request = build_request(
            method='POST',
            headers={'content-type': 'application/json'},
            body=b'{"email": "a@pythontr.com", "sayi": 3}',
        )

        self.assertEqual(
            run(parsing.parse_body(request)),
            {'email': 'a@pythontr.com', 'sayi': 3},
        )

    def test_a_json_document_that_is_not_an_object_becomes_one(self):
        request = build_request(
            method='POST',
            headers={'content-type': 'application/json'},
            body=b'[1, 2]',
        )

        self.assertEqual(
            run(parsing.parse_body(request)),
            {'non_field_errors': [1, 2]},
        )

    def test_malformed_json_is_reported_with_the_decoder_message(self):
        request = build_request(
            method='POST',
            headers={'content-type': 'application/json'},
            body=b'{"email": ',
        )

        with self.assertRaises(ValidationFailed) as caught:
            run(parsing.parse_body(request))

        self.assertEqual(caught.exception.status_code, 400)
        detail = caught.exception.body()['detail']
        self.assertTrue(detail.startswith('JSON parse error - '), detail)
        self.assertIn('Expecting value', detail)

    def test_an_undeclared_type_is_read_as_a_form(self):
        request = build_request(
            method='POST',
            headers={'content-type': 'application/x-www-form-urlencoded'},
            body=b'email=a%40pythontr.com&ad=huseyin',
        )

        self.assertEqual(
            run(parsing.parse_body(request)),
            {'email': 'a@pythontr.com', 'ad': 'huseyin'},
        )

    def test_a_repeated_form_field_collapses_into_a_list(self):
        request = build_request(
            method='POST',
            headers={'content-type': 'application/x-www-form-urlencoded'},
            body=b'categories=1&categories=2&title=bir',
        )

        self.assertEqual(
            run(parsing.parse_body(request)),
            {'categories': ['1', '2'], 'title': 'bir'},
        )

    def test_a_typeless_body_is_refused_as_text_plain(self):
        request = build_request(method='POST', body=b'{"a": 1}')

        with self.assertRaises(UnsupportedMediaType) as caught:
            run(parsing.parse_body(request, allow_form=False))

        self.assertEqual(caught.exception.status_code, 415)
        self.assertIn('text/plain', caught.exception.body()['detail'])

    def test_a_typeless_empty_body_decodes_to_an_empty_mapping(self):
        request = build_request(method='POST')

        self.assertEqual(run(parsing.parse_body(request, allow_form=False)), {})

    def test_a_json_only_route_refuses_a_form_body(self):
        request = build_request(
            method='POST',
            headers={'content-type': 'multipart/form-data; boundary=x'},
        )

        with self.assertRaises(UnsupportedMediaType) as caught:
            run(parsing.parse_body(request, allow_form=False))

        self.assertEqual(caught.exception.status_code, 415)

    def test_media_type_of_drops_the_parameters(self):
        request = build_request(
            headers={'content-type': 'Multipart/Form-Data; boundary=xyz'})

        self.assertEqual(
            parsing.media_type_of(request), 'multipart/form-data')
        self.assertTrue(parsing.is_form_request(request))

    def test_a_json_request_is_not_a_form_request(self):
        request = build_request(
            headers={'content-type': 'application/json'})

        self.assertEqual(parsing.media_type_of(request), 'application/json')
        self.assertFalse(parsing.is_form_request(request))

    def test_a_typeless_request_counts_as_a_form_request(self):
        request = build_request()

        self.assertEqual(parsing.media_type_of(request), '')
        self.assertTrue(parsing.is_form_request(request))


class Sample(BaseModel):
    email: str = Field(min_length=1)
    password: str = Field(min_length=5)
    sayi: int = 0


class FieldErrorTests(TestCase):

    def errors_for(self, **payload):
        try:
            Sample(**payload)
        except ValidationError as exc:
            return exc
        raise AssertionError('the payload validated')

    def test_missing_fields_follow_the_declared_order(self):
        exc = self.errors_for()

        body = parsing.to_field_errors(
            exc, order=parsing.field_order(Sample))

        self.assertEqual(list(body), ['email', 'password'])
        self.assertEqual(body['email'], ['Bu alan zorunlu.'])
        self.assertEqual(body['password'], ['Bu alan zorunlu.'])

    def test_without_an_order_the_errors_keep_their_own(self):
        exc = self.errors_for(email='a@pythontr.com', password='kisa')

        body = parsing.to_field_errors(exc)

        self.assertEqual(
            body,
            {'password': [
                'Bu alanın en az 5 karakter barındırdığından emin olun.']},
        )

    def test_a_bad_integer_is_reported_in_turkish(self):
        exc = self.errors_for(
            email='a@pythontr.com', password='123qwe', sayi='abc')

        body = parsing.to_field_errors(exc)

        self.assertEqual(body, {'sayi': ['Geçerli bir tam sayı giriniz.']})

    def test_field_order_reads_the_schema(self):
        self.assertEqual(
            parsing.field_order(Sample), ('email', 'password', 'sayi'))

    def test_a_unique_violation_names_the_field_and_the_model(self):
        self.assertEqual(
            parsing.unique_error('email', 'user'),
            {'email': ['Bu email alanına sahip user zaten mevcut.']},
        )

    def test_validate_returns_the_parsed_model_when_it_fits(self):
        payload = parsing.validate(
            Sample, {'email': 'a@pythontr.com', 'password': '123qwe'})

        self.assertEqual(payload.email, 'a@pythontr.com')
        self.assertEqual(payload.sayi, 0)

    def test_validate_raises_the_projects_own_failure(self):
        with self.assertRaises(ValidationFailed) as caught:
            parsing.validate(Sample, {}, order=('email', 'password'))

        self.assertEqual(caught.exception.status_code, 400)
        self.assertEqual(
            list(caught.exception.body()), ['email', 'password'])


class IterErrorsTests(TestCase):

    def test_a_nested_payload_is_flattened_in_order(self):
        detail = {
            'email': {'error': 'email_not_found'},
            'password': ['cok kisa', 'cok basit'],
        }

        self.assertEqual(
            list(iter_errors(detail)),
            ['email_not_found', 'cok kisa', 'cok basit'],
        )

    def test_a_bare_string_is_its_own_only_leaf(self):
        self.assertEqual(list(iter_errors('invalid_link')), ['invalid_link'])

    def test_leaves_are_rendered_as_strings(self):
        self.assertEqual(list(iter_errors({'sayi': [1, None]})), ['1', 'None'])


class AllowHeaderTests(TestCase):

    def test_a_request_that_was_never_stamped_advertises_nothing(self):
        self.assertIsNone(get_allow(build_request()))

    def test_the_stamped_methods_are_joined_in_order(self):
        request = build_request()

        set_allow(request, ('GET', 'HEAD', 'OPTIONS'))

        self.assertEqual(get_allow(request), 'GET, HEAD, OPTIONS')
        self.assertEqual(
            request.scope['allow_methods'], ('GET', 'HEAD', 'OPTIONS'))


class PaginateTests(TestCase):
    """``app.wire.paginate`` with paging switched on for the duration."""

    def setUp(self):
        self.results = ['a', 'b', 'c', 'd', 'e']
        patcher = patch.dict(settings.API, {'PAGE_SIZE': 2})
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_the_suite_runs_with_paging_off(self):
        with patch.dict(settings.API, {}, clear=False):
            settings.API.pop('PAGE_SIZE')
            self.assertIsNone(page_size())
            self.assertEqual(
                paginate(build_request(), self.results),
                {'results': self.results, 'unpaginated': True},
            )

    def test_the_first_page_carries_a_forward_link_only(self):
        envelope = paginate(build_request(), self.results)

        self.assertEqual(
            list(envelope),
            ['count', 'first_page', 'last_page', 'next', 'previous',
             'last_page_number', 'current_page', 'results'],
        )
        self.assertEqual(envelope['count'], 5)
        self.assertEqual(envelope['last_page_number'], 3)
        self.assertEqual(envelope['current_page'], 1)
        self.assertEqual(envelope['results'], ['a', 'b'])
        self.assertIsNone(envelope['previous'])
        self.assertIsNone(envelope['first_page'])
        self.assertEqual(envelope['next'], '/api/recipe/articles/?page=2')
        self.assertEqual(
            envelope['last_page'], '/api/recipe/articles/?page=3')

    def test_a_middle_page_links_both_ways(self):
        envelope = paginate(build_request(query='page=2'), self.results)

        self.assertEqual(envelope['current_page'], 2)
        self.assertEqual(envelope['results'], ['c', 'd'])
        self.assertEqual(envelope['previous'], '/api/recipe/articles/')
        self.assertEqual(envelope['next'], '/api/recipe/articles/?page=3')
        self.assertEqual(envelope['first_page'], '/api/recipe/articles/')

    def test_the_last_page_has_no_forward_link(self):
        envelope = paginate(build_request(query='page=3'), self.results)

        self.assertEqual(envelope['results'], ['e'])
        self.assertIsNone(envelope['next'])
        self.assertIsNone(envelope['last_page'])
        self.assertEqual(
            envelope['previous'], '/api/recipe/articles/?page=2')
        self.assertEqual(envelope['first_page'], '/api/recipe/articles/')

    def test_the_word_last_selects_the_final_page(self):
        envelope = paginate(build_request(query='page=last'), self.results)

        self.assertEqual(envelope['current_page'], 3)
        self.assertEqual(envelope['results'], ['e'])

    def test_the_other_query_parameters_survive_into_the_links(self):
        envelope = paginate(
            build_request(query='page=2&search=python'), self.results)

        self.assertEqual(
            envelope['next'], '/api/recipe/articles/?page=3&search=python')
        self.assertEqual(
            envelope['previous'], '/api/recipe/articles/?search=python')
        self.assertEqual(
            envelope['first_page'], '/api/recipe/articles/?search=python')

    def test_a_page_beyond_the_end_is_not_found(self):
        with self.assertRaises(NotFound) as caught:
            paginate(build_request(query='page=99'), self.results)

        self.assertEqual(caught.exception.status_code, 404)
        self.assertEqual(
            caught.exception.body(), {'detail': 'Geçersiz sayfa.'})

    def test_a_page_below_the_first_is_not_found(self):
        with self.assertRaises(NotFound):
            paginate(build_request(query='page=0'), self.results)

    def test_a_page_that_is_not_a_number_is_not_found(self):
        with self.assertRaises(NotFound):
            paginate(build_request(query='page=abc'), self.results)

    def test_an_empty_page_parameter_selects_the_first_page(self):
        envelope = paginate(build_request(query='page='), self.results)

        self.assertEqual(envelope['current_page'], 1)

    def test_an_empty_result_set_still_has_one_page(self):
        envelope = paginate(build_request(), [])

        self.assertEqual(envelope['count'], 0)
        self.assertEqual(envelope['last_page_number'], 1)
        self.assertEqual(envelope['results'], [])
        self.assertIsNone(envelope['next'])


class CookieTokenAuthenticationTests(TestCase):

    def setUp(self):
        self.authenticator = CookieTokenAuthentication()

    def authenticate(self, cookie=None, authorization=None):
        headers = {}
        if cookie is not None:
            headers['cookie'] = 'session=%s' % cookie
        if authorization is not None:
            headers['authorization'] = authorization
        return self.authenticator.authenticate(
            build_request(headers=headers), self.session)

    def test_it_advertises_no_scheme_which_is_why_it_answers_403(self):
        self.assertIsNone(
            self.authenticator.authenticate_header(build_request()))

    def test_no_cookie_at_all_is_not_a_credential(self):
        self.assertIsNone(self.authenticate())

    def test_a_cookie_that_is_not_json_is_ignored(self):
        self.assertIsNone(self.authenticate(cookie='cerezdegil'))

    def test_a_json_document_without_a_token_is_ignored(self):
        self.assertIsNone(
            self.authenticate(cookie=quote(json.dumps({'user': 1}))))

    def test_a_json_document_that_is_not_an_object_is_ignored(self):
        self.assertIsNone(self.authenticate(cookie=quote('[1, 2]')))

    def test_a_well_formed_cookie_holding_a_real_token_still_resolves_nobody(
            self):
        user = get_user_model().objects.create_user(
            'cerez@pythontr.com', '123qwe', is_active=True)
        token = Token(user_id=user.id)
        token.save(self.session)

        self.assertIsNone(
            self.authenticate(
                cookie=quote(json.dumps({'token': token.key}))))

    def test_a_cookie_holding_an_unknown_token_resolves_nobody(self):
        self.assertIsNone(
            self.authenticate(
                cookie=quote(json.dumps({'token': 'f' * 40}))))

    def test_a_bearer_authorization_header_is_not_read_at_all(self):
        self.assertIsNone(
            self.authenticate(authorization='Bearer %s' % ('f' * 40)))

    def test_a_token_that_is_not_a_string_is_rejected_outright(self):
        from app.wire import AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as caught:
            self.authenticate(cookie=quote(json.dumps({'token': 12345})))

        self.assertEqual(
            caught.exception.body(), {'detail': 'Geçersiz token formatı.'})


class TokenAuthenticationTests(TestCase):

    def setUp(self):
        self.authenticator = TokenAuthentication()
        self.user = get_user_model().objects.create_user(
            'simge@pythontr.com', '123qwe', is_active=True)
        self.token = Token(user_id=self.user.id)
        self.token.save(self.session)

    def authenticate(self, authorization=None):
        headers = (
            {} if authorization is None else {'authorization': authorization}
        )
        return self.authenticator.authenticate(
            build_request(headers=headers), self.session)

    def test_it_advertises_the_token_scheme(self):
        self.assertEqual(
            self.authenticator.authenticate_header(build_request()), 'Token')

    def test_a_matching_key_resolves_its_owner(self):
        user, key = self.authenticate('Token %s' % self.token.key)

        self.assertIs(user, self.user)
        self.assertEqual(key, self.token.key)

    def test_the_keyword_is_matched_without_regard_to_case(self):
        user, _key = self.authenticate('token %s' % self.token.key)

        self.assertIs(user, self.user)

    def test_no_header_is_not_a_credential(self):
        self.assertIsNone(self.authenticate())

    def test_another_scheme_is_left_to_the_next_authenticator(self):
        self.assertIsNone(self.authenticate('Bearer %s' % self.token.key))

    def test_a_keyword_without_a_key_names_the_missing_credential(self):
        from app.wire import AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as caught:
            self.authenticate('Token')

        self.assertEqual(
            caught.exception.body(),
            {'detail':
             'Geçersiz token başlığı. Kimlik bilgileri eksik.'})

    def test_a_key_with_a_space_in_it_is_named_as_such(self):
        from app.wire import AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as caught:
            self.authenticate('Token abc def')

        self.assertEqual(
            caught.exception.body(),
            {'detail':
             "Geçersiz token başlığı. Token'da boşluk olmamalı."})

    def test_an_unknown_key_is_an_invalid_token(self):
        from app.wire import AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as caught:
            self.authenticate('Token %s' % ('f' * 40))

        self.assertEqual(
            caught.exception.body(), {'detail': 'Geçersiz simge.'})

    def test_a_key_belonging_to_an_inactive_account_is_refused(self):
        self.user.is_active = False
        self.session.flush()

        from app.wire import AuthenticationFailed

        with self.assertRaises(AuthenticationFailed) as caught:
            self.authenticate('Token %s' % self.token.key)

        self.assertEqual(
            caught.exception.body(),
            {'detail': 'Kullanıcı aktif değil ya da silinmiş.'})
