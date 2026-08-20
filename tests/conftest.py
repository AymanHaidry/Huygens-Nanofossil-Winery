"""Shared fixtures for Winery tests."""

import pytest
from unittest.mock import MagicMock
import sys
import os

# Ensure winery is importable
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

@pytest.fixture
def mock_llm():
    """Return a mock Llama-like object."""
    llm = MagicMock()
    llm.create_chat_completion.return_value = {
        "choices": [{"message": {"content": '{"title":"Test"}'}}]
    }
    return llm

@pytest.fixture
def mock_env(monkeypatch):
    """Set safe env defaults for tests."""
    monkeypatch.setenv("RESEARCH_QUESTION", "Why did Concorde fail?")
    monkeypatch.setenv("RESULT_PATH", "test_result.json")
    monkeypatch.setenv("MODEL_REPO", "test/repo")
    monkeypatch.setenv("MODEL_FILE", "test.gguf")
    monkeypatch.setenv("MODEL_PATH", "models/test.gguf")
    monkeypatch.setenv("N_CTX", "4096")
    monkeypatch.setenv("N_THREADS", "1")
    monkeypatch.setenv("MAX_SEARCHES", "3")
    monkeypatch.setenv("MAX_FETCHES", "2")
    monkeypatch.setenv("MAX_CONTENT_LENGTH", "1000")
