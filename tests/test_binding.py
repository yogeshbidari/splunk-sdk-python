#!/usr/bin/env python
#
# Copyright 2011-2015 Splunk, Inc.
#
# Licensed under the Apache License, Version 2.0 (the "License"): you may
# not use this file except in compliance with the License. You may obtain
# a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
# WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
# License for the specific language governing permissions and limitations
# under the License.


from __future__ import absolute_import
from io import BytesIO
from threading import Thread

from splunklib.six.moves import BaseHTTPServer
from splunklib.six.moves.urllib.request import Request, urlopen
from splunklib.six.moves.urllib.error import HTTPError
import splunklib.six as six
from xml.etree.ElementTree import XML

import json
import logging
from tests import testlib
import unittest
import socket
import sys
import ssl
import  splunklib.six.moves.http_cookies

import splunklib.binding as binding
from splunklib.binding import HTTPError, AuthenticationError, UrlEncoded
import splunklib.data as data
from splunklib import six

import pytest

# splunkd endpoint paths
PATH_USERS = "authentication/users/"

# XML Namespaces
NAMESPACE_ATOM = "http://www.w3.org/2005/Atom"
NAMESPACE_REST = "http://dev.splunk.com/ns/rest"
NAMESPACE_OPENSEARCH = "http://a9.com/-/spec/opensearch/1.1"

# XML Extended Name Fragments
XNAMEF_ATOM = "{%s}%%s" % NAMESPACE_ATOM
XNAMEF_REST = "{%s}%%s" % NAMESPACE_REST
XNAMEF_OPENSEARCH = "{%s}%%s" % NAMESPACE_OPENSEARCH

# XML Extended Names
XNAME_AUTHOR = XNAMEF_ATOM % "author"
XNAME_ENTRY = XNAMEF_ATOM % "entry"
XNAME_FEED = XNAMEF_ATOM % "feed"
XNAME_ID = XNAMEF_ATOM % "id"
XNAME_TITLE = XNAMEF_ATOM % "title"


def load(response):
    return data.load(response.body.read())

class BindingTestCase(unittest.TestCase):
    context = None
    def setUp(self):
        logging.info("%s", self.__class__.__name__)
        self.opts = testlib.parse([], {}, ".env")
        self.context = binding.connect(**self.opts.kwargs)
        logging.debug("Connected to splunkd.")

class TestResponseReader(BindingTestCase):
    def test_empty(self):
        response = binding.ResponseReader(BytesIO(b""))
        self.assertTrue(response.empty)
        self.assertEqual(response.peek(10), b"")
        self.assertEqual(response.read(10), b"")

        arr = bytearray(10)
        self.assertEqual(response.readinto(arr), 0)
        self.assertEqual(arr, bytearray(10))
        self.assertTrue(response.empty)

    def test_read_past_end(self):
        txt = b"abcd"
        response = binding.ResponseReader(BytesIO(txt))
        self.assertFalse(response.empty)
        self.assertEqual(response.peek(10), txt)
        self.assertEqual(response.read(10), txt)
        self.assertTrue(response.empty)
        self.assertEqual(response.peek(10), b"")
        self.assertEqual(response.read(10), b"")

    def test_read_partial(self):
        txt = b"This is a test of the emergency broadcasting system."
        response = binding.ResponseReader(BytesIO(txt))
        self.assertEqual(response.peek(5), txt[:5])
        self.assertFalse(response.empty)
        self.assertEqual(response.read(), txt)
        self.assertTrue(response.empty)
        self.assertEqual(response.read(), b'')

    def test_readable(self):
        txt = "abcd"
        response = binding.ResponseReader(six.StringIO(txt))
        self.assertTrue(response.readable())

    def test_readinto_bytearray(self):
        txt = b"Checking readinto works as expected"
        response = binding.ResponseReader(BytesIO(txt))
        arr = bytearray(10)
        self.assertEqual(response.readinto(arr), 10)
        self.assertEqual(arr[:10], b"Checking r")
        self.assertEqual(response.readinto(arr), 10)
        self.assertEqual(arr[:10], b"eadinto wo")
        self.assertEqual(response.readinto(arr), 10)
        self.assertEqual(arr[:10], b"rks as exp")
        self.assertEqual(response.readinto(arr), 5)
        self.assertEqual(arr[:5], b"ected")
        self.assertTrue(response.empty)

    def test_readinto_memoryview(self):
        import sys
        if sys.version_info < (2, 7, 0):
            return  # memoryview is new to Python 2.7
        txt = b"Checking readinto works as expected"
        response = binding.ResponseReader(BytesIO(txt))
        arr = bytearray(10)
        mv = memoryview(arr)
        self.assertEqual(response.readinto(mv), 10)
        self.assertEqual(arr[:10], b"Checking r")
        self.assertEqual(response.readinto(mv), 10)
        self.assertEqual(arr[:10], b"eadinto wo")
        self.assertEqual(response.readinto(mv), 10)
        self.assertEqual(arr[:10], b"rks as exp")
        self.assertEqual(response.readinto(mv), 5)
        self.assertEqual(arr[:5], b"ected")
        self.assertTrue(response.empty)



class TestUrlEncoded(BindingTestCase):
    def test_idempotent(self):
        a = UrlEncoded('abc')
        self.assertEqual(a, UrlEncoded(a))

    def test_append(self):
        self.assertEqual(UrlEncoded('a') + UrlEncoded('b'),
                         UrlEncoded('ab'))

    def test_append_string(self):
        self.assertEqual(UrlEncoded('a') + '%',
                         UrlEncoded('a%'))

    def test_append_to_string(self):
        self.assertEqual('%' + UrlEncoded('a'),
                         UrlEncoded('%a'))

    def test_interpolation_fails(self):
        self.assertRaises(TypeError, lambda: UrlEncoded('%s') % 'boris')

    def test_chars(self):
        for char, code in [(' ', '%20'),
                           ('"', '%22'),
                           ('%', '%25')]:
            self.assertEqual(UrlEncoded(char),
                             UrlEncoded(code, skip_encode=True))

    def test_repr(self):
        self.assertEqual(repr(UrlEncoded('% %')), "UrlEncoded('% %')")

class TestAuthority(unittest.TestCase):
    def test_authority_default(self):
        self.assertEqual(binding._authority(),
                         "https://localhost:8089")

    def test_ipv4_host(self):
        self.assertEqual(
            binding._authority(
                host="splunk.utopia.net"),
            "https://splunk.utopia.net:8089")

    def test_ipv6_host(self):
        self.assertEqual(
            binding._authority(
                host="2001:0db8:85a3:0000:0000:8a2e:0370:7334"),
            "https://[2001:0db8:85a3:0000:0000:8a2e:0370:7334]:8089")

    def test_ipv6_host_enclosed(self):
        self.assertEqual(
            binding._authority(
                host="[2001:0db8:85a3:0000:0000:8a2e:0370:7334]"),
            "https://[2001:0db8:85a3:0000:0000:8a2e:0370:7334]:8089")

    def test_all_fields(self):
        self.assertEqual(
            binding._authority(
                scheme="http",
                host="splunk.utopia.net",
                port="471"),
            "http://splunk.utopia.net:471")

class TestUserManipulation(BindingTestCase):
    def setUp(self):
        BindingTestCase.setUp(self)
        self.username = testlib.tmpname()
        self.password = "changeme!"
        self.roles = "power"

        # Delete user if it exists already
        try:
            response = self.context.delete(PATH_USERS + self.username)
            self.assertEqual(response.status, 200)
        except HTTPError as e:
            self.assertTrue(e.status in [400, 500])

    def tearDown(self):
        BindingTestCase.tearDown(self)
        try:
            self.context.delete(PATH_USERS + self.username)
        except HTTPError as e:
            if e.status not in [400, 500]:
                raise

    def test_user_without_role_fails(self):
        self.assertRaises(binding.HTTPError,
                          self.context.post,
                          PATH_USERS, name=self.username,
                          password=self.password)

    def test_create_user(self):
        response = self.context.post(
            PATH_USERS, name=self.username,
            password=self.password, roles=self.roles)
        self.assertEqual(response.status, 201)

        response = self.context.get(PATH_USERS + self.username)
        entry = load(response).feed.entry
        self.assertEqual(entry.title, self.username)

    def test_update_user(self):
        self.test_create_user()
        response = self.context.post(
            PATH_USERS + self.username,
            password=self.password,
            roles=self.roles,
            defaultApp="search",
            realname="Renzo",
            email="email.me@now.com")
        self.assertEqual(response.status, 200)

        response = self.context.get(PATH_USERS + self.username)
        self.assertEqual(response.status, 200)
        entry = load(response).feed.entry
        self.assertEqual(entry.title, self.username)
        self.assertEqual(entry.content.defaultApp, "search")
        self.assertEqual(entry.content.realname, "Renzo")
        self.assertEqual(entry.content.email, "email.me@now.com")

    def test_post_with_body_behaves(self):
        self.test_create_user()
        response = self.context.post(
            PATH_USERS + self.username,
            body="defaultApp=search",
        )
        self.assertEqual(response.status, 200)

    def test_post_with_get_arguments_to_receivers_stream(self):
        text = 'Hello, world!'
        response = self.context.post(
            '/services/receivers/simple',
            headers=[('x-splunk-input-mode', 'streaming')],
            source='sdk', sourcetype='sdk_test',
            body=text
        )
        self.assertEqual(response.status, 200)


class TestSocket(BindingTestCase):
    def test_socket(self):
        socket = self.context.connect()
        socket.write(("POST %s HTTP/1.1\r\n" % \
                         self.context._abspath("some/path/to/post/to")).encode('utf-8'))
        socket.write(("Host: %s:%s\r\n" % \
                         (self.context.host, self.context.port)).encode('utf-8'))
        socket.write("Accept-Encoding: identity\r\n".encode('utf-8'))
        socket.write(("Authorization: %s\r\n" % \
                         self.context.token).encode('utf-8'))
        socket.write("X-Splunk-Input-Mode: Streaming\r\n".encode('utf-8'))
        socket.write("\r\n".encode('utf-8'))
        socket.close()

    # Sockets take bytes not strings
    #
    # def test_unicode_socket(self):
    #     socket = self.context.connect()
    #     socket.write(u"POST %s HTTP/1.1\r\n" %\
    #                  self.context._abspath("some/path/to/post/to"))
    #     socket.write(u"Host: %s:%s\r\n" %\
    #                  (self.context.host, self.context.port))
    #     socket.write(u"Accept-Encoding: identity\r\n")
    #     socket.write((u"Authorization: %s\r\n" %\
    #                  self.context.token).encode('utf-8'))
    #     socket.write(u"X-Splunk-Input-Mode: Streaming\r\n")
    #     socket.write("\r\n")
    #     socket.close()

    def test_socket_gethostbyname(self):
        self.assertTrue(self.context.connect())
        self.context.host = socket.gethostbyname(self.context.host)
        self.assertTrue(self.context.connect())

class TestUnicodeConnect(BindingTestCase):
    def test_unicode_connect(self):
        opts = self.opts.kwargs.copy()
        opts['host'] = six.text_type(opts['host'])
        context = binding.connect(**opts)
        # Just check to make sure the service is alive
        response = context.get("/services")
        self.assertEqual(response.status, 200)

@pytest.mark.smoke
class TestAutologin(BindingTestCase):
    def test_with_autologin(self):
        self.context.autologin = True
        self.assertEqual(self.context.get("/services").status, 200)
        self.context.logout()
        self.assertEqual(self.context.get("/services").status, 200)

    def test_without_autologin(self):
        self.context.autologin = False
        self.assertEqual(self.context.get("/services").status, 200)
        self.context.logout()
        self.assertRaises(AuthenticationError,
                          self.context.get, "/services")

class TestAbspath(BindingTestCase):
    def setUp(self):
        BindingTestCase.setUp(self)
        self.kwargs = self.opts.kwargs.copy()
        if 'app' in self.kwargs: del self.kwargs['app']
        if 'owner' in self.kwargs: del self.kwargs['owner']


    def test_default(self):
        path = self.context._abspath("foo", owner=None, app=None)
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/services/foo")

    def test_with_owner(self):
        path = self.context._abspath("foo", owner="me", app=None)
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me/system/foo")

    def test_with_app(self):
        path = self.context._abspath("foo", owner=None, app="MyApp")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/MyApp/foo")

    def test_with_both(self):
        path = self.context._abspath("foo", owner="me", app="MyApp")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me/MyApp/foo")

    def test_user_sharing(self):
        path = self.context._abspath("foo", owner="me", app="MyApp", sharing="user")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me/MyApp/foo")

    def test_sharing_app(self):
        path = self.context._abspath("foo", owner="me", app="MyApp", sharing="app")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/MyApp/foo")

    def test_sharing_global(self):
        path = self.context._abspath("foo", owner="me", app="MyApp",sharing="global")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/MyApp/foo")

    def test_sharing_system(self):
        path = self.context._abspath("foo bar", owner="me", app="MyApp",sharing="system")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/system/foo%20bar")

    def test_url_forbidden_characters(self):
        path = self.context._abspath('/a/b c/d')
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, '/a/b%20c/d')

    def test_context_defaults(self):
        context = binding.connect(**self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/services/foo")

    def test_context_with_owner(self):
        context = binding.connect(owner="me", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me/system/foo")

    def test_context_with_app(self):
        context = binding.connect(app="MyApp", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/MyApp/foo")

    def test_context_with_both(self):
        context = binding.connect(owner="me", app="MyApp", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me/MyApp/foo")

    def test_context_with_user_sharing(self):
        context = binding.connect(
            owner="me", app="MyApp", sharing="user", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me/MyApp/foo")

    def test_context_with_app_sharing(self):
        context = binding.connect(
            owner="me", app="MyApp", sharing="app", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/MyApp/foo")

    def test_context_with_global_sharing(self):
        context = binding.connect(
            owner="me", app="MyApp", sharing="global", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/MyApp/foo")

    def test_context_with_system_sharing(self):
        context = binding.connect(
            owner="me", app="MyApp", sharing="system", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/nobody/system/foo")

    def test_context_with_owner_as_email(self):
        context = binding.connect(owner="me@me.com", **self.kwargs)
        path = context._abspath("foo")
        self.assertTrue(isinstance(path, UrlEncoded))
        self.assertEqual(path, "/servicesNS/me%40me.com/system/foo")
        self.assertEqual(path, UrlEncoded("/servicesNS/me@me.com/system/foo"))

# An urllib2 based HTTP request handler, used to test the binding layers
# support for pluggable request handlers.
def urllib2_handler(url, message, **kwargs):
    method = message['method'].lower()
    data = message.get('body', b"") if method == 'post' else None
    headers = dict(message.get('headers', []))
    req = Request(url, data, headers)
    try:
        # If running Python 2.7.9+, disable SSL certificate validation
        if sys.version_info >= (2, 7, 9):
            response = urlopen(req, context=ssl._create_unverified_context())
        else:
            response = urlopen(req)
    except HTTPError as response:
        pass # Propagate HTTP errors via the returned response message
    return {
        'status': response.code,
        'reason': response.msg,
        'headers': dict(response.info()),
        'body': BytesIO(response.read())
    }

def isatom(body):
    """Answers if the given response body looks like ATOM."""
    root = XML(body)
    return \
        root.tag == XNAME_FEED and \
        root.find(XNAME_AUTHOR) is not None and \
        root.find(XNAME_ID) is not None and \
        root.find(XNAME_TITLE) is not None

class TestPluggableHTTP(testlib.SDKTestCase):
    # Verify pluggable HTTP reqeust handlers.
    def test_handlers(self):
        paths = ["/services", "authentication/users",
                 "search/jobs"]
        handlers = [binding.handler(),  # default handler
                    urllib2_handler]
        for handler in handlers:
            logging.debug("Connecting with handler %s", handler)
            context = binding.connect(
                handler=handler,
                **self.opts.kwargs)
            for path in paths:
                body = context.get(path).body.read()
                self.assertTrue(isatom(body))

def urllib2_insert_cookie_handler(url, message, **kwargs):
    method = message['method'].lower()
    data = message.get('body', b"") if method == 'post' else None
    headers = dict(message.get('headers', []))
    req = Request(url, data, headers)
    try:
        # If running Python 2.7.9+, disable SSL certificate validation
        if sys.version_info >= (2, 7, 9):
            response = urlopen(req, context=ssl._create_unverified_context())
        else:
            response = urlopen(req)
    except HTTPError as response:
        pass # Propagate HTTP errors via the returned response message

    # Mimic the insertion of 3rd party cookies into the response.
    # An example is "sticky session"/"insert cookie" persistence
    # of a load balancer for a SHC.
    header_list = [(k, v) for k, v in response.info().items()] 
    header_list.append(("Set-Cookie", "BIGipServer_splunk-shc-8089=1234567890.12345.0000; path=/; Httponly; Secure"))
    header_list.append(("Set-Cookie", "home_made=yummy"))
    
    return {
        'status': response.code,
        'reason': response.msg,
        'headers': header_list,
        'body': BytesIO(response.read())
    }

class TestCookiePersistence(testlib.SDKTestCase):
    # Verify persistence of 3rd party inserted cookies.
    def test_3rdPartyInsertedCookiePersistence(self):
        paths = ["/services", "authentication/users",
                 "search/jobs"]
        logging.debug("Connecting with urllib2_insert_cookie_handler %s", urllib2_insert_cookie_handler)
        context = binding.connect(
            handler=urllib2_insert_cookie_handler,
            **self.opts.kwargs)

        persisted_cookies = context.get_cookies()

        splunk_token_found = False
        for k, v in persisted_cookies.items():
            if k[:8] == "splunkd_":
                splunk_token_found = True
                break

        self.assertEqual(splunk_token_found, True)
        self.assertEqual(persisted_cookies['BIGipServer_splunk-shc-8089'], "1234567890.12345.0000")
        self.assertEqual(persisted_cookies['home_made'], "yummy")

@pytest.mark.smoke
class TestLogout(BindingTestCase):
    def test_logout(self):
        response = self.context.get("/services")
        self.assertEqual(response.status, 200)
        self.context.logout()
        self.assertEqual(self.context.token, binding._NoAuthenticationToken)
        self.assertEqual(self.context.get_cookies(), {})
        self.assertRaises(AuthenticationError,
                          self.context.get, "/services")
        self.assertRaises(AuthenticationError,
                          self.context.post, "/services")
        self.assertRaises(AuthenticationError,
                          self.context.delete, "/services")
        self.context.login()
        response = self.context.get("/services")
        self.assertEqual(response.status, 200)


class TestCookieAuthentication(unittest.TestCase):
    def setUp(self):
        self.opts = testlib.parse([], {}, ".env")
        self.context = binding.connect(**self.opts.kwargs)

        # Skip these tests if running below Splunk 6.2, cookie-auth didn't exist before
        import splunklib.client as client
        service = client.Service(**self.opts.kwargs)
        # TODO: Workaround the fact that skipTest is not defined by unittest2.TestCase
        service.login()
        splver = service.splunk_version
        if splver[:2] < (6, 2):
            self.skipTest("Skipping cookie-auth tests, running in %d.%d.%d, this feature was added in 6.2+" % splver)

    if getattr(unittest.TestCase, 'assertIsNotNone', None) is None:

        def assertIsNotNone(self, obj, msg=None):
            if obj is None:
                raise self.failureException(msg or '%r is not None' % obj)

    @pytest.mark.smoke
    def test_cookie_in_auth_headers(self):
        self.assertIsNotNone(self.context._auth_headers)
        self.assertNotEqual(self.context._auth_headers, [])
        self.assertEqual(len(self.context._auth_headers), 1)
        self.assertEqual(len(self.context._auth_headers), 1)
        self.assertEqual(self.context._auth_headers[0][0], "Cookie")
        self.assertEqual(self.context._auth_headers[0][1][:8], "splunkd_")

    @pytest.mark.smoke
    def test_got_cookie_on_connect(self):
        self.assertIsNotNone(self.context.get_cookies())
        self.assertNotEqual(self.context.get_cookies(), {})
        self.assertEqual(len(self.context.get_cookies()), 1)
        self.assertEqual(list(self.context.get_cookies().keys())[0][:8], "splunkd_")

    @pytest.mark.smoke
    def test_cookie_with_autologin(self):
        self.context.autologin = True
        self.assertEqual(self.context.get("/services").status, 200)
        self.assertTrue(self.context.has_cookies())
        self.context.logout()
        self.assertFalse(self.context.has_cookies())
        self.assertEqual(self.context.get("/services").status, 200)
        self.assertTrue(self.context.has_cookies())

    @pytest.mark.smoke
    def test_cookie_without_autologin(self):
        self.context.autologin = False
        self.assertEqual(self.context.get("/services").status, 200)
        self.assertTrue(self.context.has_cookies())
        self.context.logout()
        self.assertFalse(self.context.has_cookies())
        self.assertRaises(AuthenticationError,
                          self.context.get, "/services")

    @pytest.mark.smoke
    def test_got_updated_cookie_with_get(self):
        old_cookies = self.context.get_cookies()
        resp = self.context.get("apps/local")
        found = False
        for key, value in resp.headers:
            if key.lower() == "set-cookie":
                found = True
                self.assertEqual(value[:8], "splunkd_")

                new_cookies = {}
                binding._parse_cookies(value, new_cookies)
                # We're only expecting 1 in this scenario
                self.assertEqual(len(old_cookies), 1)
                self.assertTrue(len(list(new_cookies.values())), 1)
                self.assertEqual(old_cookies, new_cookies)
                self.assertEqual(list(new_cookies.values())[0], list(old_cookies.values())[0])
        self.assertTrue(found)

    @pytest.mark.smoke
    def test_login_fails_with_bad_cookie(self):
        # We should get an error if using a bad cookie
        try:
            new_context = binding.connect(**{"cookie": "bad=cookie"})
            self.fail()
        except AuthenticationError as ae:
            self.assertEqual(str(ae), "Login failed.")

    @pytest.mark.smoke
    def test_login_with_multiple_cookies(self):
        # We should get an error if using a bad cookie
        new_context = binding.Context()
        new_context.get_cookies().update({"bad": "cookie"})
        try:
            new_context = new_context.login()
            self.fail()
        except AuthenticationError as ae:
            self.assertEqual(str(ae), "Login failed.")
            # Bring in a valid cookie now
            for key, value in self.context.get_cookies().items():
                new_context.get_cookies()[key] = value

            self.assertEqual(len(new_context.get_cookies()), 2)
            self.assertTrue('bad' in list(new_context.get_cookies().keys()))
            self.assertTrue('cookie' in list(new_context.get_cookies().values()))

            for k, v in self.context.get_cookies().items():
                self.assertEqual(new_context.get_cookies()[k], v)

            self.assertEqual(new_context.get("apps/local").status, 200)

    @pytest.mark.smoke
    def test_login_fails_without_cookie_or_token(self):
        opts = {
            'host': self.opts.kwargs['host'],
            'port': self.opts.kwargs['port']
        }
        try:
            binding.connect(**opts)
            self.fail()
        except AuthenticationError as ae:
            self.assertEqual(str(ae), "Login failed.")


class TestNamespace(unittest.TestCase):
    def test_namespace(self):
        tests = [
            ({ },
             { 'sharing': None, 'owner': None, 'app': None }),

            ({ 'owner': "Bob" },
             { 'sharing': None, 'owner': "Bob", 'app': None }),

            ({ 'app': "search" },
             { 'sharing': None, 'owner': None, 'app': "search" }),

            ({ 'owner': "Bob", 'app': "search" },
             { 'sharing': None, 'owner': "Bob", 'app': "search" }),

            ({ 'sharing': "user", 'owner': "Bob@bob.com" },
             { 'sharing': "user", 'owner': "Bob@bob.com", 'app': None }),

            ({ 'sharing': "user" },
             { 'sharing': "user", 'owner': None, 'app': None }),

            ({ 'sharing': "user", 'owner': "Bob" },
             { 'sharing': "user", 'owner': "Bob", 'app': None }),

            ({ 'sharing': "user", 'app': "search" },
             { 'sharing': "user", 'owner': None, 'app': "search" }),

            ({ 'sharing': "user", 'owner': "Bob", 'app': "search" },
             { 'sharing': "user", 'owner': "Bob", 'app': "search" }),

            ({ 'sharing': "app" },
             { 'sharing': "app", 'owner': "nobody", 'app': None }),

            ({ 'sharing': "app", 'owner': "Bob" },
             { 'sharing': "app", 'owner': "nobody", 'app': None }),

            ({ 'sharing': "app", 'app': "search" },
             { 'sharing': "app", 'owner': "nobody", 'app': "search" }),

            ({ 'sharing': "app", 'owner': "Bob", 'app': "search" },
             { 'sharing': "app", 'owner': "nobody", 'app': "search" }),

            ({ 'sharing': "global" },
             { 'sharing': "global", 'owner': "nobody", 'app': None }),

            ({ 'sharing': "global", 'owner': "Bob" },
             { 'sharing': "global", 'owner': "nobody", 'app': None }),

            ({ 'sharing': "global", 'app': "search" },
             { 'sharing': "global", 'owner': "nobody", 'app': "search" }),

            ({ 'sharing': "global", 'owner': "Bob", 'app': "search" },
             { 'sharing': "global", 'owner': "nobody", 'app': "search" }),

            ({ 'sharing': "system" },
             { 'sharing': "system", 'owner': "nobody", 'app': "system" }),

            ({ 'sharing': "system", 'owner': "Bob" },
             { 'sharing': "system", 'owner': "nobody", 'app': "system" }),

            ({ 'sharing': "system", 'app': "search" },
             { 'sharing': "system", 'owner': "nobody", 'app': "system" }),

            ({ 'sharing': "system", 'owner': "Bob",    'app': "search" },
             { 'sharing': "system", 'owner': "nobody", 'app': "system" }),

            ({ 'sharing': 'user',   'owner': '-',      'app': '-'},
             { 'sharing': 'user',   'owner': '-',      'app': '-'})]

        for kwargs, expected in tests:
            namespace = binding.namespace(**kwargs)
            for k, v in six.iteritems(expected):
                self.assertEqual(namespace[k], v)

    def test_namespace_fails(self):
        self.assertRaises(ValueError, binding.namespace, sharing="gobble")

@pytest.mark.smoke
class TestBasicAuthentication(unittest.TestCase):
    def setUp(self):
        self.opts = testlib.parse([], {}, ".env")
        opts = self.opts.kwargs.copy()
        opts["basic"] = True
        opts["username"] = self.opts.kwargs["username"]
        opts["password"] = self.opts.kwargs["password"]

        self.context = binding.connect(**opts)
        import splunklib.client as client
        service = client.Service(**opts)

    if getattr(unittest.TestCase, 'assertIsNotNone', None) is None:
        def assertIsNotNone(self, obj, msg=None):
           if obj is None:
               raise self.failureException(msg or '%r is not None' % obj)

    def test_basic_in_auth_headers(self):
        self.assertIsNotNone(self.context._auth_headers)
        self.assertNotEqual(self.context._auth_headers, [])
        self.assertEqual(len(self.context._auth_headers), 1)
        self.assertEqual(len(self.context._auth_headers), 1)
        self.assertEqual(self.context._auth_headers[0][0], "Authorization")
        self.assertEqual(self.context._auth_headers[0][1][:6], "Basic ")
        self.assertEqual(self.context.get("/services").status, 200)

@pytest.mark.smoke
class TestTokenAuthentication(BindingTestCase):
    def test_preexisting_token(self):
        token = self.context.token
        opts = self.opts.kwargs.copy()
        opts["token"] = token
        opts["username"] = "boris the mad baboon"
        opts["password"] = "nothing real"

        newContext = binding.Context(**opts)
        response = newContext.get("/services")
        self.assertEqual(response.status, 200)

        socket = newContext.connect()
        socket.write(("POST %s HTTP/1.1\r\n" % \
                         self.context._abspath("some/path/to/post/to")).encode('utf-8'))
        socket.write(("Host: %s:%s\r\n" % \
                         (self.context.host, self.context.port)).encode('utf-8'))
        socket.write(("Accept-Encoding: identity\r\n").encode('utf-8'))
        socket.write(("Authorization: %s\r\n" % \
                         self.context.token).encode('utf-8'))
        socket.write("X-Splunk-Input-Mode: Streaming\r\n".encode('utf-8'))
        socket.write(("\r\n").encode('utf-8'))
        socket.close()

    def test_preexisting_token_sans_splunk(self):
        token = self.context.token
        if token.startswith('Splunk '):
            token = token.split(' ', 1)[1]
            self.assertFalse(token.startswith('Splunk '))
        else:
            self.fail('Token did not start with "Splunk ".')
        opts = self.opts.kwargs.copy()
        opts["token"] = token
        opts["username"] = "boris the mad baboon"
        opts["password"] = "nothing real"

        newContext = binding.Context(**opts)
        response = newContext.get("/services")
        self.assertEqual(response.status, 200)

        socket = newContext.connect()
        socket.write(("POST %s HTTP/1.1\r\n" %\
                    self.context._abspath("some/path/to/post/to")).encode('utf-8'))
        socket.write(("Host: %s:%s\r\n" %\
                     (self.context.host, self.context.port)).encode('utf-8'))
        socket.write("Accept-Encoding: identity\r\n".encode('utf-8'))
        socket.write(("Authorization: %s\r\n" %\
                     self.context.token).encode('utf-8'))
        socket.write(("X-Splunk-Input-Mode: Streaming\r\n").encode('utf-8'))
        socket.write(("\r\n").encode('utf-8'))
        socket.close()


    def test_connect_with_preexisting_token_sans_user_and_pass(self):
        token = self.context.token
        opts = self.opts.kwargs.copy()
        del opts['username']
        del opts['password']
        opts["token"] = token

        newContext = binding.connect(**opts)
        response = newContext.get('/services')
        self.assertEqual(response.status, 200)

        socket = newContext.connect()
        socket.write(("POST %s HTTP/1.1\r\n" % \
                         self.context._abspath("some/path/to/post/to")).encode('utf-8'))
        socket.write(("Host: %s:%s\r\n" % \
                         (self.context.host, self.context.port)).encode('utf-8'))
        socket.write("Accept-Encoding: identity\r\n".encode('utf-8'))
        socket.write(("Authorization: %s\r\n" % \
                         self.context.token).encode('utf-8'))
        socket.write("X-Splunk-Input-Mode: Streaming\r\n".encode('utf-8'))
        socket.write("\r\n".encode('utf-8'))
        socket.close()


class TestPostWithBodyParam(unittest.TestCase):

    def test_post(self):
        def handler(url, message, **kwargs):
            assert six.ensure_str(url) == "https://localhost:8089/servicesNS/testowner/testapp/foo/bar"
            assert six.ensure_str(message["body"]) == "testkey=testvalue"
            return splunklib.data.Record({
                "status": 200,
                "headers": [],
            })
        ctx = binding.Context(handler=handler)
        ctx.post("foo/bar", owner="testowner", app="testapp", body={"testkey": "testvalue"})

    def test_post_with_params_and_body(self):
        def handler(url, message, **kwargs):
            assert url == "https://localhost:8089/servicesNS/testowner/testapp/foo/bar?extrakey=extraval"
            assert six.ensure_str(message["body"]) == "testkey=testvalue"
            return splunklib.data.Record({
                "status": 200,
                "headers": [],
            })
        ctx = binding.Context(handler=handler)
        ctx.post("foo/bar", extrakey="extraval", owner="testowner", app="testapp", body={"testkey": "testvalue"})

    def test_post_with_params_and_no_body(self):
        def handler(url, message, **kwargs):
            assert url == "https://localhost:8089/servicesNS/testowner/testapp/foo/bar"
            assert six.ensure_str(message["body"]) == "extrakey=extraval"
            return splunklib.data.Record({
                "status": 200,
                "headers": [],
            })
        ctx = binding.Context(handler=handler)
        ctx.post("foo/bar", extrakey="extraval", owner="testowner", app="testapp")


def _wrap_handler(func, response_code=200, body=""):
    def wrapped(handler_self):
        result = func(handler_self)
        if result is None:
            handler_self.send_response(response_code)
            handler_self.end_headers()
            handler_self.wfile.write(body)
    return wrapped


class MockServer(object):
    def __init__(self, port=9093, **handlers):
        methods = {"do_" + k: _wrap_handler(v) for (k, v) in handlers.items()}

        def init(handler_self, socket, address, server):
            BaseHTTPServer.BaseHTTPRequestHandler.__init__(handler_self, socket, address, server)

        def log(*args):  # To silence server access logs
            pass

        methods["__init__"] = init
        methods["log_message"] = log
        Handler = type("Handler",
                       (BaseHTTPServer.BaseHTTPRequestHandler, object),
                       methods)
        self._svr = BaseHTTPServer.HTTPServer(("localhost", port), Handler)

        def run():
            self._svr.handle_request()
        self._thread = Thread(target=run)
        self._thread.daemon = True

    def __enter__(self):
        self._thread.start()
        return self._svr

    def __exit__(self, typ, value, traceback):
        self._thread.join(10)
        self._svr.server_close()


class TestFullPost(unittest.TestCase):

    def test_post_with_body_urlencoded(self):
        def check_response(handler):
            length = int(handler.headers.get('content-length', 0))
            body = handler.rfile.read(length)
            assert six.ensure_str(body) == "foo=bar"

        with MockServer(POST=check_response):
            ctx = binding.connect(port=9093, scheme='http', token="waffle")
            ctx.post("/", foo="bar")

    def test_post_with_body_string(self):
        def check_response(handler):
            length = int(handler.headers.get('content-length', 0))
            body = handler.rfile.read(length)
            assert six.ensure_str(handler.headers['content-type']) == 'application/json'
            assert json.loads(body)["baz"] == "baf"

        with MockServer(POST=check_response):
            ctx = binding.connect(port=9093, scheme='http', token="waffle", headers=[("Content-Type", "application/json")])
            ctx.post("/", foo="bar", body='{"baz": "baf"}')

    def test_post_with_body_dict(self):
        def check_response(handler):
            length = int(handler.headers.get('content-length', 0))
            body = handler.rfile.read(length)
            assert six.ensure_str(handler.headers['content-type']) == 'application/x-www-form-urlencoded'
            assert six.ensure_str(body) == 'baz=baf&hep=cat' or six.ensure_str(body) == 'hep=cat&baz=baf'

        with MockServer(POST=check_response):
            ctx = binding.connect(port=9093, scheme='http', token="waffle")
            ctx.post("/", foo="bar", body={"baz": "baf", "hep": "cat"})


if __name__ == "__main__":
    try:
        import unittest2 as unittest
    except ImportError:
        import unittest
    unittest.main()
