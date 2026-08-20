"""Tests for winery/main.py — orchestration layer.

Mocks llama-cpp-python entirely (heavy native deps).
"""

import pytest
import json
import os
from unittest.mock import patch, MagicMock, mock_open
from winery import main


class TestCleanResponse:
    def test_strips_think_tags(self):
        text = "<think>hidden reasoning</think>Actual answer"
        cleaned = main.clean_response(text)
        assert "hidden reasoning" not in cleaned
        assert "Actual answer" in cleaned

    def test_strips_reasoning_section(self):
        text = "Answer\n\nReasoning: because of X"
        cleaned = main.clean_response(text)
        assert "because of X" not in cleaned
        assert "Answer" in cleaned

    def test_handles_empty_and_none(self):
        assert main.clean_response("") == ""
        assert main.clean_response(None) == ""


class TestParseJson:
    def test_markdown_json_fence(self):
        text = '''```json
{"key": "value"}
```'''
        assert main.parse_json(text) == {"key": "value"}

    def test_plain_json(self):
        text = '{"key": "value"}'
        assert main.parse_json(text) == {"key": "value"}

    def test_malformed_returns_none(self):
        assert main.parse_json("not json") is None

    def test_partial_json_returns_none(self):
        assert main.parse_json('{"key": "val') is None


class TestEnsureModel:
    def test_uses_existing_file(self, tmp_path, monkeypatch):
        model_path = tmp_path / "test.gguf"
        model_path.write_bytes(b"x" * 2_000_000)
        monkeypatch.setattr(main, "MODEL_PATH", str(model_path))
        result = main.ensure_model()
        assert result == str(model_path)

    def test_downloads_when_missing(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "MODEL_PATH", str(tmp_path / "missing.gguf"))
        monkeypatch.setattr(main, "MODEL_REPO", "test/repo")
        monkeypatch.setattr(main, "MODEL_FILE", "model.gguf")

        with patch("winery.main.hf_hub_download", return_value=str(tmp_path / "model.gguf")) as mock_dl:
            result = main.ensure_model()
            mock_dl.assert_called_once()
            assert "model.gguf" in result

    def test_exits_on_download_failure(self, tmp_path, monkeypatch):
        monkeypatch.setattr(main, "MODEL_PATH", str(tmp_path / "missing.gguf"))
        with patch("winery.main.hf_hub_download", side_effect=Exception("fail")):
            with pytest.raises(SystemExit) as exc:
                main.ensure_model()
            assert exc.value.code == 1


class TestLoadLlm:
    def test_loads_successfully(self, tmp_path):
        with patch("winery.main.Llama") as MockLlama:
            mock_instance = MagicMock()
            MockLlama.return_value = mock_instance
            llm = main.load_llm(str(tmp_path / "model.gguf"))
            MockLlama.assert_called_once()
            assert llm == mock_instance

    def test_exits_on_import_error(self):
        with patch.dict("sys.modules", {"llama_cpp": None}):
            with pytest.raises(SystemExit) as exc:
                main.load_llm("model.gguf")
            assert exc.value.code == 1

    def test_exits_on_load_failure(self, tmp_path):
        with patch("winery.main.Llama", side_effect=Exception("OOM")):
            with pytest.raises(SystemExit) as exc:
                main.load_llm(str(tmp_path / "model.gguf"))
            assert exc.value.code == 1


class TestCallLlm:
    def test_success(self, mock_llm):
        result = main.call_llm(mock_llm, [{"role": "user", "content": "hi"}])
        assert result == '{"title":"Test"}'
        mock_llm.create_chat_completion.assert_called_once()

    def test_empty_on_failure(self, mock_llm):
        mock_llm.create_chat_completion.side_effect = Exception("fail")
        result = main.call_llm(mock_llm, [])
        assert result == ""


class TestGeneratePlan:
    def test_parses_json_list(self, mock_llm):
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": '["q1", "q2", "q3"]'}}]
        }
        plan = main.generate_plan(mock_llm, "question")
        assert plan == ["q1", "q2", "q3"]

    def test_fallback_to_question(self, mock_llm):
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "not json"}}]
        }
        plan = main.generate_plan(mock_llm, "my question")
        assert plan == ["my question"]

    def test_respects_max_searches(self, mock_llm, monkeypatch):
        monkeypatch.setattr(main, "MAX_SEARCHES", 2)
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": '["a","b","c","d","e"]'}}]
        }
        plan = main.generate_plan(mock_llm, "q")
        assert len(plan) == 2


class TestExecuteSearches:
    @patch("winery.main.search_web")
    def test_collects_unique_sources(self, mock_search):
        from winery.tools import SearchResult
        mock_search.side_effect = [
            [SearchResult("T1", "http://a.com", "S1")],
            [SearchResult("T2", "http://b.com", "S2")],
        ]
        with patch("winery.main.is_valid_source", return_value=True):
            sources = main.execute_searches(["q1", "q2"])
        assert len(sources) == 2
        assert sources[0].title == "T1"

    @patch("winery.main.search_web")
    def test_warns_on_few_sources(self, mock_search, capsys):
        mock_search.return_value = []
        sources = main.execute_searches(["q1"])
        assert len(sources) == 0
        captured = capsys.readouterr()
        assert "Very few sources" in captured.out or "Very few sources" in captured.err


class TestFetchSources:
    def test_prioritizes_primary(self):
        from winery.models import Source
        s1 = Source("T1", "http://a.com", "secondary", snippet="snip")
        s2 = Source("T2", "http://b.com", "primary", snippet="snip")

        with patch("winery.main.fetch_page") as mock_fetch:
            mock_fetch.return_value = MagicMock(text="Content text here", title="Fetched")
            sources = main.fetch_sources([s1, s2])

        # s2 (primary) should have fetched_text because it's sorted first
        assert sources[1].fetched_text

    def test_respects_max_fetches(self, monkeypatch):
        monkeypatch.setattr(main, "MAX_FETCHES", 1)
        from winery.models import Source
        srcs = [Source(f"T{i}", f"http://{i}.com", "secondary") for i in range(3)]

        with patch("winery.main.fetch_page") as mock_fetch:
            mock_fetch.return_value = MagicMock(text="x" * 500, title="T")
            sources = main.fetch_sources(srcs)

        fetched_count = sum(1 for s in sources if s.fetched_text)
        assert fetched_count == 1


class TestSynthesize:
    def test_full_pipeline(self, mock_llm):
        from winery.models import Source
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": json.dumps({
                "title": "Report",
                "executive_summary": "ES",
                "key_findings": [{"title": "F1", "content": "C1"}],
                "evidence_assessment": "EA",
                "confidence_notes": "CN",
                "sources": [{"title": "S1", "url": "http://a.com", "type": "primary"}]
            })}}]
        }
        sources = [Source("S1", "http://a.com", "primary", fetched_text="text")]
        report = main.synthesize(mock_llm, "Q?", sources)
        assert report.title == "Report"
        assert len(report.key_findings) == 1
        assert report.key_findings[0].title == "F1"

    def test_fallback_on_bad_json(self, mock_llm):
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "not json"}}]
        }
        from winery.models import Source
        sources = [Source("S", "http://a.com", "primary")]
        report = main.synthesize(mock_llm, "Q", sources)
        assert "formatting issue" in report.executive_summary
        assert len(report.key_findings) == 1
        assert report.key_findings[0].title == "Analysis"


class TestBuildFallback:
    def test_structure(self):
        from winery.models import Source
        sources = [Source("S", "http://a.com", "primary")]
        report = main.build_fallback("Q?", sources, "raw text here")
        assert report.title == "Research: Q?"
        assert "formatting issue" in report.executive_summary
        assert report.key_findings[0].content == "raw text here"


class TestSimpleTest:
    def test_outputs_response(self, mock_llm, capsys):
        mock_llm.create_chat_completion.return_value = {
            "choices": [{"message": {"content": "I am Nanofossil."}}]
        }
        result = main.simple_test(mock_llm, "hello")
        assert result == "I am Nanofossil."
        captured = capsys.readouterr()
        assert "Nanofossil" in captured.out


class TestMain:
    def test_no_question_runs_simple_test(self, monkeypatch, mock_llm, capsys, tmp_path):
        monkeypatch.setattr(main, "RESEARCH_QUESTION", "")
        monkeypatch.setattr(main, "MODEL_PATH", str(tmp_path / "model.gguf"))

        with patch("winery.main.ensure_model", return_value=str(tmp_path / "model.gguf")):
            with patch("winery.main.load_llm", return_value=mock_llm):
                main.main()

        captured = capsys.readouterr()
        assert "Simple Test Mode" in captured.out

    def test_short_question_runs_simple_test(self, monkeypatch, mock_llm, tmp_path):
        monkeypatch.setattr(main, "RESEARCH_QUESTION", "test")
        monkeypatch.setattr(main, "MODEL_PATH", str(tmp_path / "model.gguf"))

        with patch("winery.main.ensure_model", return_value=str(tmp_path / "model.gguf")):
            with patch("winery.main.load_llm", return_value=mock_llm):
                main.main()

    def test_full_pipeline(self, monkeypatch, mock_llm, tmp_path):
        monkeypatch.setattr(main, "RESEARCH_QUESTION", "Why did Concorde fail commercially?")
        monkeypatch.setattr(main, "RESULT_PATH", str(tmp_path / "out.json"))
        monkeypatch.setattr(main, "MODEL_PATH", str(tmp_path / "model.gguf"))

        with patch("winery.main.ensure_model", return_value=str(tmp_path / "model.gguf")):
            with patch("winery.main.load_llm", return_value=mock_llm):
                with patch("winery.main.generate_plan", return_value=["q1"]):
                    with patch("winery.main.execute_searches") as mock_search:
                        from winery.models import Source
                        mock_search.return_value = [Source("S", "http://a.com", "primary")]
                        with patch("winery.main.fetch_sources", side_effect=lambda x: x):
                            with patch("winery.main.synthesize") as mock_syn:
                                from winery.models import ResearchReport
                                mock_syn.return_value = ResearchReport(
                                    title="R", executive_summary="ES",
                                    key_findings=[], sources=[], question="Q"
                                )
                                main.main()

        assert (tmp_path / "out.json").exists()

    def test_failure_writes_error_json(self, monkeypatch, mock_llm, tmp_path):
        monkeypatch.setattr(main, "RESEARCH_QUESTION", "Q")
        monkeypatch.setattr(main, "RESULT_PATH", str(tmp_path / "out.json"))
        monkeypatch.setattr(main, "MODEL_PATH", str(tmp_path / "model.gguf"))

        with patch("winery.main.ensure_model", side_effect=Exception("boom")):
            with pytest.raises(SystemExit) as exc:
                main.main()
            assert exc.value.code == 1

        with open(tmp_path / "out.json") as f:
            data = json.load(f)
        assert data["job"]["status"] == "failed"
        assert "boom" in data["job"]["error"]
