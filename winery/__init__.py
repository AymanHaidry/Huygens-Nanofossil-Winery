"""
Winery — Autonomous Research Agent for Nanofossil
=================================================
A zero-API-cost research pipeline that runs Qwen3-4B locally
on GitHub Actions and turns questions into structured,
cross-checked, sourced JSON reports.

Pipeline
--------
1. DECOMPOSE  → Break question into search angles
2. RESEARCH   → DuckDuckGo + fetch + strip
3. CROSSCHECK → Surface conflicts / verify dates
4. SYNTHESIZE → Reason over evidence with Qwen3-4B
5. WRITE      → Emit structured JSON dossier

Usage
-----
    python -m winery "Why did Concorde fail commercially?"

Env vars
--------
    RESEARCH_QUESTION   The question to investigate
    MODEL_PATH          Path to GGUF (default: models/qwen3-4b-q4_k_m.gguf)
    N_CTX               Context size (default: 8192)
    RESULTS_DIR         Where to write JSON (default: results)
"""

from __future__ import annotations

import json
import os
import re
import sys
import textwrap
import time
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from html.parser import HTMLParser
from pathlib import Path
from typing import Any

import requests


# ── Configuration ──────────────────────────────────────────────────────

DEFAULT_MODEL = "models/Qwen3-4B-Q4_K_M.gguf"
DEFAULT_N_CTX = 8192
DEFAULT_RESULTS = "results"
MAX_SEARCH_RESULTS = 5
FETCH_TIMEOUT = 12
MAX_CONTENT_LEN = 6000  # chars per page
MAX_EVIDENCE_TOKENS = 4000  # rough char budget for synthesis


# ── HTML text extractor (stdlib only) ────────────────────────────────────

class _TextExtractor(HTMLParser):
    """Minimal HTML → plain-text stripper. No external deps."""

    def __init__(self) -> None:
        super().__init__()
        self._text: list[str] = []
        self._skip = 0
        self._skip_tags = {"script", "style", "nav", "footer", "header", "aside", "noscript"}

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in self._skip_tags:
            self._skip += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._skip_tags:
            self._skip -= 1

    def handle_data(self, data: str) -> None:
        if self._skip <= 0:
            self._text.append(data)

    def get_text(self) -> str:
        raw = " ".join(self._text)
        # collapse whitespace
        return re.sub(r"\s+", " ", raw).strip()


def strip_html(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:
        # Fallback: regex strip tags
        return re.sub(r"<[^>]+>", " ", html)
    return parser.get_text()


# ── Data structures ──────────────────────────────────────────────────────

@dataclass
class Source:
    title: str
    url: str
    snippet: str = ""
    content: str = ""
    source_type: str = "secondary"


@dataclass
class Angle:
    query: str
    rationale: str


@dataclass
class Finding:
    title: str
    content: str


@dataclass
class Report:
    title: str
    question: str
    generated_at: str
    executive_summary: str = ""
    key_findings: list[Finding] = field(default_factory=list)
    evidence_assessment: str = ""
    confidence_notes: str = ""
    sources: list[Source] = field(default_factory=list)
    comparison: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "question": self.question,
            "generated_at": self.generated_at,
            "executive_summary": self.executive_summary,
            "key_findings": [{"title": f.title, "content": f.content} for f in self.key_findings],
            "evidence_assessment": self.evidence_assessment,
            "confidence_notes": self.confidence_notes,
            "sources": [
                {"title": s.title, "url": s.url, "type": s.source_type}
                for s in self.sources
            ],
            "comparison": self.comparison,
        }


# ── LLM wrapper ────────────────────────────────────────────────────────

class LLM:
    """Thin wrapper around llama-cpp-python."""

    def __init__(self, model_path: str, n_ctx: int = DEFAULT_N_CTX) -> None:
        self.model_path = Path(model_path)
        self.n_ctx = n_ctx
        self._llm: Any = None

    def _ensure_model(self) -> None:
        if self.model_path.exists():
            return
        # Auto-download from HuggingFace if missing
        print(f"[Winery] Model not found at {self.model_path}. Attempting download...")
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        url = (
            "https://huggingface.co/Qwen/Qwen3-4B-GGUF/resolve/main/"
            "qwen3-4b-q4_k_m.gguf"
        )
        print(f"[Winery] Downloading from {url}")
        r = requests.get(url, stream=True, timeout=300)
        r.raise_for_status()
        with open(self.model_path, "wb") as f:
            for chunk in r.iter_content(chunk_size=8192):
                f.write(chunk)
        print(f"[Winery] Model saved to {self.model_path}")

    def load(self) -> None:
        from llama_cpp import Llama

        self._ensure_model()
        print(f"[Winery] Loading model: {self.model_path}")
        self._llm = Llama(
            model_path=str(self.model_path),
            n_ctx=self.n_ctx,
            n_threads=int(os.getenv("LLAMA_THREADS", os.cpu_count() or 4)),
            verbose=False,
        )
        print("[Winery] Model ready.")

    def generate(
        self,
        prompt: str,
        system: str = "",
        max_tokens: int = 2048,
        temperature: float = 0.35,
    ) -> str:
        if self._llm is None:
            raise RuntimeError("Model not loaded. Call .load() first.")

        messages = []
        if system:
            messages.append({"role": "system", "content": system})
        messages.append({"role": "user", "content": prompt})

        out = self._llm.create_chat_completion(
            messages=messages,
            max_tokens=max_tokens,
            temperature=temperature,
            stop=["<|im_end|>", "<|endoftext|>"],
        )
        return out["choices"][0]["message"]["content"].strip()


# ── DuckDuckGo search ────────────────────────────────────────────────────

def search_web(query: str, max_results: int = MAX_SEARCH_RESULTS) -> list[Source]:
    """Search DuckDuckGo and return sources."""
    try:
        from duckduckgo_search import DDGS
    except ImportError as exc:
        raise ImportError(
            "duckduckgo-search is required. Install: pip install duckduckgo-search"
        ) from exc

    results: list[Source] = []
    with DDGS() as ddgs:
        for r in ddgs.text(query, max_results=max_results):
            results.append(
                Source(
                    title=r.get("title", "Untitled"),
                    url=r.get("href", ""),
                    snippet=r.get("body", ""),
                )
            )
    return results


def fetch_page(url: str, timeout: int = FETCH_TIMEOUT) -> str:
    """Fetch and strip HTML to plain text."""
    try:
        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            )
        }
        r = requests.get(url, headers=headers, timeout=timeout)
        r.raise_for_status()
        text = strip_html(r.text)
        return text[:MAX_CONTENT_LEN]
    except Exception as exc:
        return f"[Fetch error: {exc}]"


# ── Prompts ──────────────────────────────────────────────────────────────

SYSTEM_DECOMPOSE = textwrap.dedent(
    """    You are Winery, an autonomous research decomposition engine.
    Break the user's question into 3–5 precise search angles.
    Each angle must be a single query string a search engine could answer.
    Output ONLY a JSON array: [{"query":"...","rationale":"..."}, ...]
    No markdown, no commentary outside JSON."""
)

SYSTEM_CROSSCHECK = textwrap.dedent(
    """    You are Winery's evidence auditor.
    Given raw evidence snippets, identify:
    1. Conflicting claims
    2. Dates or facts that seem inconsistent
    3. Sources that appear weak or circular
    Output a short bullet list. Be concise."""
)

SYSTEM_SYNTHESIZE = textwrap.dedent(
    """    You are Winery's synthesis engine.
    Given verified evidence, produce a structured research report.
    Output MUST be valid JSON with this exact schema:
    {
      "title": "...",
      "executive_summary": "...",
      "key_findings": [
        {"title": "...", "content": "..."}
      ],
      "evidence_assessment": "...",
      "confidence_notes": "..."
    }
    No markdown outside JSON. Use the evidence provided. Cite sources by number."""
)


# ── Winery Agent ─────────────────────────────────────────────────────────

class Winery:
    """The autonomous research pipeline."""

    def __init__(
        self,
        model_path: str | None = None,
        n_ctx: int = DEFAULT_N_CTX,
    ) -> None:
        self.model_path = model_path or os.getenv("MODEL_PATH", DEFAULT_MODEL)
        self.n_ctx = n_ctx
        self.llm = LLM(self.model_path, n_ctx)
        self._sources: list[Source] = []

    # ── Stage 1: Decompose ──────────────────────────────────────────────

    def decompose(self, question: str) -> list[Angle]:
        print("[Stage 1] Decomposing question...")
        prompt = f"Question: {question}\n\nGenerate search angles."
        raw = self.llm.generate(prompt, system=SYSTEM_DECOMPOSE, temperature=0.3)
        # Extract JSON
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)
        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: heuristic split
            data = [{"query": question, "rationale": "Direct search"}]

        angles = [Angle(q=a["query"], rationale=a.get("rationale", "")) for a in data]
        print(f"[Stage 1] {len(angles)} angles generated.")
        return angles

    # ── Stage 2: Research ───────────────────────────────────────────────

    def research(self, angles: list[Angle]) -> list[Source]:
        print("[Stage 2] Researching sources...")
        all_sources: list[Source] = []
        seen_urls: set[str] = set()

        for angle in angles:
            try:
                results = search_web(angle.query, max_results=MAX_SEARCH_RESULTS)
            except Exception as exc:
                print(f"  [Search error] {exc}")
                continue

            for r in results:
                if r.url in seen_urls or not r.url.startswith("http"):
                    continue
                seen_urls.add(r.url)
                print(f"  Fetching: {r.url[:80]}...")
                r.content = fetch_page(r.url)
                # Simple source-type heuristic
                if any(d in r.url for d in [".edu", ".gov", "arxiv", "nature", "science"]):
                    r.source_type = "primary"
                all_sources.append(r)
                time.sleep(0.4)  # be polite to servers

        self._sources = all_sources
        print(f"[Stage 2] {len(all_sources)} unique sources fetched.")
        return all_sources

    # ── Stage 3: Cross-check ──────────────────────────────────────────────

    def cross_check(self, sources: list[Source]) -> str:
        print("[Stage 3] Cross-checking evidence...")
        # Build evidence block
        evidence_block = ""
        for i, s in enumerate(sources[:15], 1):
            evidence_block += f"\n[{i}] {s.title}\n{s.content[:600]}\n"

        prompt = f"Evidence:\n{evidence_block}\n\nAudit this evidence."
        audit = self.llm.generate(prompt, system=SYSTEM_CROSSCHECK, max_tokens=1024)
        print("[Stage 3] Cross-check complete.")
        return audit

    # ── Stage 4: Synthesize ───────────────────────────────────────────────

    def synthesize(self, sources: list[Source], audit: str, question: str) -> Report:
        print("[Stage 4] Synthesizing findings...")

        # Build compact evidence string within token budget
        evidence_str = ""
        budget = MAX_EVIDENCE_TOKENS
        for i, s in enumerate(sources[:15], 1):
            chunk = f"\n[{i}] {s.title} ({s.source_type})\n{s.content[:500]}\n"
            if len(evidence_str) + len(chunk) > budget:
                break
            evidence_str += chunk

        prompt = textwrap.dedent(
            f"""            Research Question: {question}

            Evidence Audit:
            {audit}

            Evidence:
            {evidence_str}

            Produce the JSON report now."""
        )

        raw = self.llm.generate(prompt, system=SYSTEM_SYNTHESIZE, max_tokens=3000)
        # Extract JSON
        raw = raw.strip()
        if raw.startswith("```"):
            raw = re.sub(r"^```(?:json)?\s*", "", raw)
            raw = re.sub(r"\s*```$", "", raw)

        try:
            data = json.loads(raw)
        except json.JSONDecodeError:
            # Fallback: wrap raw text into a basic report
            data = {
                "title": question,
                "executive_summary": raw[:800],
                "key_findings": [{"title": "Primary finding", "content": raw[:1200]}],
                "evidence_assessment": "Generated from raw synthesis.",
                "confidence_notes": "Medium — LLM may have hallucinated details.",
            }

        report = Report(
            title=data.get("title", question),
            question=question,
            generated_at=datetime.now(timezone.utc).isoformat(),
            executive_summary=data.get("executive_summary", ""),
            key_findings=[
                Finding(title=f["title"], content=f["content"])
                for f in data.get("key_findings", [])
            ],
            evidence_assessment=data.get("evidence_assessment", ""),
            confidence_notes=data.get("confidence_notes", ""),
            sources=sources,
        )
        print("[Stage 4] Synthesis complete.")
        return report

    # ── Stage 5: Write ────────────────────────────────────────────────────

    def write(self, report: Report, run_id: str | None = None) -> Path:
        print("[Stage 5] Writing report...")
        out_dir = Path(os.getenv("RESULTS_DIR", DEFAULT_RESULTS))
        out_dir.mkdir(parents=True, exist_ok=True)
        run_id = run_id or str(uuid.uuid4())[:8]
        out_path = out_dir / f"{run_id}.json"

        payload = report.to_dict()
        payload["run_id"] = run_id
        payload["pipeline_version"] = "winery-1.0"

        with open(out_path, "w", encoding="utf-8") as f:
            json.dump(payload, f, indent=2, ensure_ascii=False)

        print(f"[Stage 5] Report saved: {out_path}")
        return out_path

    # ── Full pipeline ───────────────────────────────────────────────────

    def run(self, question: str, run_id: str | None = None) -> Path:
        self.llm.load()
        angles = self.decompose(question)
        sources = self.research(angles)
        audit = self.cross_check(sources)
        report = self.synthesize(sources, audit, question)
        return self.write(report, run_id)


# ── CLI entry point ──────────────────────────────────────────────────────

def main() -> None:
    question = os.getenv("RESEARCH_QUESTION", " ".join(sys.argv[1:]))
    if not question:
        print("Usage: python -m winery <question>")
        print("   or: RESEARCH_QUESTION="..." python -m winery")
        sys.exit(1)

    run_id = os.getenv("GITHUB_RUN_ID", str(uuid.uuid4())[:8])
    agent = Winery()
    agent.run(question, run_id=run_id)


if __name__ == "__main__":
    main()
