"""Tests for winery/models.py — data layer."""

import json
from datetime import datetime
from freezegun import freeze_time
from winery.models import Source, Finding, Comparison, ResearchReport, ResearchJob


class TestSource:
    def test_to_dict_excludes_fetched_text(self):
        """fetched_text is internal; to_dict should not leak it."""
        s = Source(title="T", url="http://x.com", type="primary", snippet="snip", fetched_text="secret")
        d = s.to_dict()
        assert "fetched_text" not in d
        assert d["snippet"] == "snip"

    def test_defaults(self):
        s = Source(title="T", url="http://x.com", type="secondary")
        assert s.snippet == ""
        assert s.fetched_text == ""


class TestFinding:
    def test_to_dict(self):
        f = Finding(title="F1", content="Details")
        assert f.to_dict() == {"title": "F1", "content": "Details"}


class TestComparison:
    def test_to_dict(self):
        c = Comparison(headers=["A", "B"], rows=[["1", "2"]])
        assert c.to_dict() == {"headers": ["A", "B"], "rows": [["1", "2"]]}


class TestResearchReport:
    @freeze_time("2024-01-15T12:00:00")
    def test_to_dict_structure(self):
        r = ResearchReport(
            title="R",
            executive_summary="ES",
            key_findings=[Finding("F", "C")],
            sources=[Source("S", "http://x.com", "primary")],
            question="Q?",
        )
        d = r.to_dict()
        assert d["title"] == "R"
        assert d["generated_at"] == "2024-01-15T12:00:00"
        assert len(d["key_findings"]) == 1
        assert len(d["sources"]) == 1
        assert "comparison" not in d  # optional field omitted when None

    @freeze_time("2024-01-15T12:00:00")
    def test_to_dict_with_comparison(self):
        r = ResearchReport(
            title="R", executive_summary="ES", key_findings=[],
            comparison=Comparison(["A"], [["1"]]),
            sources=[], question="Q",
        )
        d = r.to_dict()
        assert d["comparison"] == {"headers": ["A"], "rows": [["1"]]}

    def test_to_json_roundtrip(self):
        r = ResearchReport(
            title="R", executive_summary="ES", key_findings=[],
            sources=[], question="Q",
        )
        j = r.to_json()
        data = json.loads(j)
        assert data["report"]["title"] == "R"


class TestResearchJob:
    def test_defaults(self):
        j = ResearchJob(question="Q?")
        assert j.status == "pending"
        assert j.plan == []
        assert j.sources == []
        assert j.error is None

