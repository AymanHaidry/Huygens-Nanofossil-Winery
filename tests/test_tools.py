"""Tests for winery/tools.py — web layer."""

import pytest
from unittest.mock import patch, MagicMock
import responses
from winery.tools import (
    search_web, fetch_page, is_valid_source, classify_source,
    SearchResult, PageContent
)


class TestSearchWeb:
    @patch("winery.tools.HAS_DDGS", True)
    def test_success(self):
        mock_ddgs = MagicMock()
        mock_ddgs.__enter__ = MagicMock(return_value=mock_ddgs)
        mock_ddgs.__exit__ = MagicMock(return_value=False)
        mock_ddgs.text.return_value = [
            {"title": "T1", "href": "http://a.com", "body": "B1"},
            {"title": "T2", "href": "http://b.com", "body": "B2"},
        ]

        with patch("winery.tools.DDGS", return_value=mock_ddgs):
            results = search_web("query", max_results=5)
        
        assert len(results) == 2
        assert results[0].title == "T1"
        assert results[0].url == "http://a.com"

    @patch("winery.tools.HAS_DDGS", False)
    def test_skips_when_ddgs_missing(self):
        results = search_web("query")
        assert results == []

    @patch("winery.tools.HAS_DDGS", True)
    def test_exception_handling(self):
        with patch("winery.tools.DDGS", side_effect=Exception("network")):
            results = search_web("query")
        assert results == []


class TestFetchPage:
    @responses.activate
    def test_success(self):
        html = "<html><head><title>Page</title></head><body><p>Hello world</p></body></html>"
        responses.add(responses.GET, "http://example.com", body=html, status=200,
                      content_type="text/html")
        
        page = fetch_page("http://example.com")
        assert page is not None
        assert page.title == "Page"
        assert "Hello world" in page.text
        assert page.url == "http://example.com"

    @responses.activate
    def test_pdf_returns_placeholder(self):
        responses.add(responses.GET, "http://example.com/doc.pdf", body=b"%PDF",
                      status=200, content_type="application/pdf")
        
        page = fetch_page("http://example.com/doc.pdf")
        assert page is not None
        assert page.meta["type"] == "pdf"
        assert "[PDF document" in page.text

    @responses.activate
    def test_timeout(self):
        responses.add(responses.GET, "http://slow.com", body=Exception("timeout"))
        # requests mock via responses doesn't easily simulate timeout; patch at lower level
        with patch("winery.tools.requests.get", side_effect=Exception("timeout")):
            page = fetch_page("http://slow.com", timeout=1)
        assert page is None

    @responses.activate
    def test_404(self):
        responses.add(responses.GET, "http://example.com", status=404)
        page = fetch_page("http://example.com")
        assert page is None

    @responses.activate
    def test_truncates_long_content(self):
        long_html = "<html><body><p>" + "x" * 60000 + "</p></body></html>"
        responses.add(responses.GET, "http://long.com", body=long_html, status=200)
        
        page = fetch_page("http://long.com")
        assert len(page.text) <= 50050  # 50000 + truncation notice

    @responses.activate
    def test_extracts_meta_description(self):
        html = '<html><head><meta name="description" content="Desc"></head><body><p>Text</p></body></html>'
        responses.add(responses.GET, "http://meta.com", body=html, status=200)
        
        page = fetch_page("http://meta.com")
        assert page.meta.get("description") == "Desc"


class TestIsValidSource:
    @pytest.mark.parametrize("url,expected", [
        ("https://arxiv.org/abs/1234", True),
        ("https://en.wikipedia.org/wiki/X", True),
        ("https://reddit.com/r/x", False),
        ("https://twitter.com/user", False),
        ("https://x.com/user", False),
        ("https://youtube.com/watch", False),
    ])
    def test_classification(self, url, expected):
        assert is_valid_source(url) == expected


class TestClassifySource:
    def test_primary_gov(self):
        assert classify_source("https://sec.gov/rules") == "primary"

    def test_primary_edu(self):
        assert classify_source("https://mit.edu/research") == "primary"

    def test_primary_arxiv(self):
        assert classify_source("https://arxiv.org/abs/1234") == "primary"

    def test_secondary_wikipedia(self):
        assert classify_source("https://wikipedia.org/wiki/X") == "secondary"

    def test_secondary_blog(self):
        assert classify_source("https://blog.example.com/post") == "secondary"

    def test_secondary_news(self):
        assert classify_source("https://news.bbc.com/article") == "secondary"

    def test_default_secondary(self):
        assert classify_source("https://unknown.com") == "secondary"
