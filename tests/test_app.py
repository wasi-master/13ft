"""Offline regression tests. Run: python -m unittest discover -s tests -v."""
import json
import os
import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "app"))
import portable as web

ARTICLE = "<html><head><title>Article</title></head><body><p>Useful article content.</p></body></html>"
URL = "https://example.com/news/article"


class AppTests(unittest.TestCase):
    def setUp(self):
        self.env = patch.dict(os.environ, {"LOCALE": "en"})
        self.env.start()
        self.addCleanup(self.env.stop)
        self.network = patch.object(web.requests.sessions.Session, "request", side_effect=AssertionError("Unexpected network access"))
        self.network.start()
        self.addCleanup(self.network.stop)
        web.jobs.clear()
        web.page_cache.clear()
        web.load_strings_for_locale.cache_clear()
        self.addCleanup(web.jobs.clear)
        self.addCleanup(web.page_cache.clear)
        self.addCleanup(web.load_strings_for_locale.cache_clear)
        self.client = web.app.test_client()
        self.strings = web.load_strings()

    def test_home_renders_form(self):
        response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Enter Website Link", response.data)
        self.assertIn(b'<form', response.data)

    def test_portuguese_home(self):
        with patch.dict(os.environ, {"LOCALE": "pt"}):
            response = self.client.get("/")
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'lang="pt"', response.data)

    def test_unknown_locale_falls_back_to_english(self):
        with patch.dict(os.environ, {"LOCALE": "nonexistent"}):
            self.assertEqual(web.load_strings()["lang"], "en")

    def test_locale_path_traversal_falls_back(self):
        with patch.dict(os.environ, {"LOCALE": "../../etc/passwd"}):
            self.assertEqual(web.get_locale(), "en")

    def test_article_post_returns_processed_result(self):
        with patch.object(web, "bypass_paywall", return_value=ARTICLE) as fetch:
            response = self.client.post("/article", data={"link": URL})
        self.assertEqual(response.status_code, 200)
        self.assertIn(b"Useful article content", response.data)
        fetch.assert_called_once_with(URL, self.strings)

    def test_article_requires_link(self):
        self.assertEqual(self.client.post("/article", data={}).status_code, 400)

    def test_article_errors_are_user_facing(self):
        cases = [
            (web.requests.exceptions.Timeout(), "timeout_error", 400),
            (web.requests.exceptions.ConnectionError(), "connection_error", 400),
            (web.requests.exceptions.RequestException(), "request_error", 400),
            (RuntimeError("private details"), "unexpected_error", 500),
        ]
        for error, message, status in cases:
            with self.subTest(error=type(error).__name__), patch.object(web, "bypass_paywall", side_effect=error):
                response = self.client.post("/article", data={"link": URL})
                self.assertEqual(response.status_code, status)
                self.assertEqual(response.get_data(as_text=True), self.strings[message])

    def test_article_custom_error(self):
        with patch.object(web, "bypass_paywall", side_effect=web.UserFacingError("Unavailable")):
            response = self.client.post("/article", data={"link": URL})
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.get_data(as_text=True), "Unavailable")

    def test_cached_article_avoids_fetch(self):
        web.page_cache[URL] = {"html": ARTICLE, "timestamp": web.time.time()}
        with patch.object(web, "bypass_paywall") as fetch:
            response = self.client.get("/" + URL)
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.get_data(as_text=True), ARTICLE)
        fetch.assert_not_called()

    def test_status_requires_url(self):
        self.assertEqual(self.client.get("/status").status_code, 400)

    def test_status_stream_success_and_cleanup(self):
        def start(thread):
            thread._target(*thread._args, **thread._kwargs)
        with patch.object(web.threading.Thread, "start", start), patch.object(web, "bypass_paywall", return_value=ARTICLE):
            response = self.client.get("/status", query_string={"url": URL})
            body = response.get_data(as_text=True)
        self.assertEqual(response.mimetype, "text/event-stream")
        event = json.loads(body.split("data: ", 1)[1].strip())
        self.assertEqual(event, {"step": "done", "redirect": "/" + URL})
        self.assertEqual(web.jobs, {})
        self.assertEqual(web.page_cache[URL]["html"], ARTICLE)

    def test_status_stream_failure_and_cleanup(self):
        def start(thread):
            thread._target(*thread._args, **thread._kwargs)
        with patch.object(web.threading.Thread, "start", start), patch.object(web, "bypass_paywall", side_effect=web.requests.exceptions.Timeout()):
            response = self.client.get("/status", query_string={"url": URL})
            body = response.get_data(as_text=True)
        self.assertIn("event: error_msg", body)
        self.assertIn(self.strings["timeout_error"], body)
        self.assertEqual(web.jobs, {})
        self.assertEqual(web.page_cache, {})

    def test_html_fixes_relative_links(self):
        soup = web.BeautifulSoup(web.process_html_document(ARTICLE, URL), "html.parser")
        self.assertEqual(soup.base["href"], "https://example.com/news/")
        self.assertIn("Useful article content", soup.get_text())

    def test_html_replaces_existing_base(self):
        source = '<html><head><base href="/"></head><body>Article</body></html>'
        soup = web.BeautifulSoup(web.process_html_document(source, URL), "html.parser")
        self.assertEqual(len(soup.find_all("base")), 1)
        self.assertEqual(soup.base["href"], "https://example.com/news/")

    def test_direct_fetch_adds_scheme_and_googlebot(self):
        response = Mock(status_code=200, text=ARTICLE, url=URL, apparent_encoding="utf-8")
        with patch.object(web.requests, "get", return_value=response) as get:
            result = web.bypass_paywall("example.com/news/article", self.strings)
        get.assert_called_once_with(URL, headers=web.googlebot_headers, timeout=30)
        self.assertIn("Useful article content", result)

    def test_blocked_response_uses_archive(self):
        response = Mock(status_code=403, text="Blocked", url=URL)
        with patch.object(web.requests, "get", return_value=response), patch.object(web, "fetch_via_archive_org", return_value=(ARTICLE, URL)) as archive, patch.object(web, "fetch_via_archive_ph") as fallback:
            result = web.bypass_paywall(URL, self.strings)
        self.assertIn("Useful article content", result)
        archive.assert_called_once_with(URL, None)
        fallback.assert_not_called()

    def test_second_archive_is_used_when_first_is_empty(self):
        response = Mock(status_code=403, text="Blocked", url=URL)
        with patch.object(web.requests, "get", return_value=response), patch.object(web, "fetch_via_archive_org", return_value=(None, None)), patch.object(web, "fetch_via_archive_ph", return_value=(ARTICLE, URL)) as fallback:
            self.assertIn("Useful article content", web.bypass_paywall(URL, self.strings))
        fallback.assert_called_once_with(URL, None)

    def test_all_archives_empty_raise_user_error(self):
        response = Mock(status_code=403, text="Blocked", url=URL)
        with patch.object(web.requests, "get", return_value=response), patch.object(web, "fetch_via_archive_org", return_value=(None, None)), patch.object(web, "fetch_via_archive_ph", return_value=(None, None)):
            with self.assertRaises(web.UserFacingError) as error:
                web.bypass_paywall(URL, self.strings)
        self.assertEqual(str(error.exception), self.strings["challenge_error"])

    def test_medium_uses_freedium_before_direct_fetch(self):
        with patch.object(web, "fetch_via_freedium", return_value=(ARTICLE, URL)), patch.object(web.requests, "get") as get:
            self.assertIn("Useful article content", web.bypass_paywall("https://medium.com/story", self.strings))
        get.assert_not_called()

    def test_cache_removes_only_expired_entries(self):
        web.page_cache.update({"old": {"timestamp": 0}, "fresh": {"timestamp": 999}})
        with patch.object(web.time, "time", return_value=1000):
            web.clean_page_cache()
        self.assertNotIn("old", web.page_cache)
        self.assertIn("fresh", web.page_cache)


if __name__ == "__main__":
    unittest.main()
