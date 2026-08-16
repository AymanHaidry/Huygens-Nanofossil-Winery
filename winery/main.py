#!/usr/bin/env python3
"""Winery — Star1's backend orchestration layer.

Huygens presents Star1.
Runs the research pipeline on a self-hosted Qwen3-4B model
inside a GitHub Actions ephemeral runner.

Pipeline: Question → Plan → Search → Fetch → Synthesize → Output
"""

import os
import sys
import json
import re
import time
from typing import List, Dict, Optional

from prompts import STAR1_SYSTEM_PROMPT, RESEARCH_PLAN_PROMPT, SYNTHESIS_PROMPT, SIMPLE_TEST_PROMPT
from tools import search_web, fetch_page, classify_source, is_valid_source
from models import ResearchReport, Source, Finding, Comparison, ResearchJob

# ─── Configuration ───

RESEARCH_QUESTION = os.environ.get("RESEARCH_QUESTION", "").strip()
RESULT_PATH = os.environ.get("RESULT_PATH", "result.json")

MODEL_REPO = os.environ.get("MODEL_REPO", "bartowski/Qwen_Qwen3-4B-GGUF")
MODEL_FILE = os.environ.get("MODEL_FILE", "Qwen_Qwen3-4B-Q4_K_M.gguf")
MODEL_PATH = os.environ.get("MODEL_PATH", f"models/{MODEL_FILE}")

N_CTX = int(os.environ.get("N_CTX", "8192"))
N_THREADS = int(os.environ.get("N_THREADS", "2"))
MAX_SEARCHES = int(os.environ.get("MAX_SEARCHES", "5"))
MAX_FETCHES = int(os.environ.get("MAX_FETCHES", "6"))
MAX_CONTENT_LENGTH = int(os.environ.get("MAX_CONTENT_LENGTH", "6000"))

# ─── Logging helpers ───

def log(msg: str):
    print(f"[Winery] {msg}")

def log_error(msg: str, detail: str = None):
    print(f"[Winery] ERROR: {msg}", file=sys.stderr)
    if detail:
        print(f"[Winery]   → {detail}", file=sys.stderr)

def log_section(title: str):
    print(f"\n{'─' * 40}")
    print(f"[Winery] {title}")
    print(f"{'─' * 40}")

# ─── Model loading ───

def ensure_model() -> str:
    """Ensure the GGUF model is available locally. Download if needed."""
    if os.path.exists(MODEL_PATH) and os.path.getsize(MODEL_PATH) > 1_000_000:
        log(f"Model found: {MODEL_PATH}")
        return MODEL_PATH

    log("Model not found locally. Attempting download...")
    log(f"  Repo: {MODEL_REPO}")
    log(f"  File: {MODEL_FILE}")

    try:
        from huggingface_hub import hf_hub_download
        os.makedirs("models", exist_ok=True)
        downloaded = hf_hub_download(
            repo_id=MODEL_REPO,
            filename=MODEL_FILE,
            local_dir="models/",
            local_dir_use_symlinks=False
        )
        log(f"Model downloaded to: {downloaded}")
        return downloaded
    except Exception as e:
        log_error("Failed to download model", str(e))
        log("Troubleshooting:")
        log("  • Check MODEL_REPO and MODEL_FILE env vars.")
        log("  • Verify the model exists on Hugging Face.")
        log("  • If gated, set HF_TOKEN in secrets.")
        sys.exit(1)


def load_llm(model_path: str):
    """Load the quantized model with llama-cpp-python."""
    try:
        from llama_cpp import Llama
    except ImportError:
        log_error("llama-cpp-python not installed", "Run: pip install llama-cpp-python")
        sys.exit(1)

    log(f"Loading model...")
    log(f"  Path: {model_path}")
    log(f"  Context: {N_CTX} tokens")
    log(f"  Threads: {N_THREADS}")

    try:
        llm = Llama(
            model_path=model_path,
            n_ctx=N_CTX,
            n_threads=N_THREADS,
            verbose=False,
        )
        log("Model loaded successfully.")
        return llm
    except Exception as e:
        log_error("Failed to load model", str(e))
        log("Troubleshooting:")
        log("  • The model file may be corrupt. Re-download it.")
        log("  • The runner may not have enough RAM for this model.")
        log("  • Try a smaller quantization (e.g., Q4_0 instead of Q4_K_M).")
        sys.exit(1)


def call_llm(llm, messages: List[Dict], temperature: float = 0.3, max_tokens: int = 2048) -> str:
    """Call the local model and return cleaned text."""
    try:
        response = llm.create_chat_completion(
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
        )
        text = response["choices"][0]["message"]["content"]
        return clean_response(text)
    except Exception as e:
        log_error("Model inference failed", str(e))
        return ""


def clean_response(text: str) -> str:
    """Strip Qwen3 think tags and clean up output."""
    if not text:
        return ""
    # Remove think tags
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    text = re.sub(r"<thinking>.*?</thinking>", "", text, flags=re.DOTALL)
    # Remove reasoning tags
    text = re.sub(r"\s*Reasoning:.*?(?=\n\n|\Z)", "", text, flags=re.DOTALL)
    return text.strip()

# ─── JSON parsing ───

def parse_json(text: str) -> Optional[Dict]:
    """Extract JSON from model response."""
    # Try markdown fences
    for pattern in [r"```json\s*(.*?)```", r"```\s*(.*?)```"]:
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group(1).strip())
            except json.JSONDecodeError:
                continue
    # Try raw
    try:
        return json.loads(text.strip())
    except json.JSONDecodeError:
        pass
    return None

# ─── Research pipeline ───

def generate_plan(llm, question: str) -> List[str]:
    """Generate search queries from the research question."""
    log("Planning research...")
    prompt = RESEARCH_PLAN_PROMPT.format(question=question)
    messages = [
        {"role": "system", "content": STAR1_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    response = call_llm(llm, messages, temperature=0.4, max_tokens=512)
    plan = parse_json(response)
    if plan and isinstance(plan, list):
        queries = [q for q in plan if isinstance(q, str) and len(q) > 3]
        log(f"Plan ready: {len(queries)} queries")
        return queries[:MAX_SEARCHES]
    log("Could not parse research plan. Using fallback.")
    return [question]


def execute_searches(queries: List[str]) -> List[Source]:
    """Run web searches and collect unique sources."""
    log("Searching sources...")
    all_results = []
    seen_urls = set()

    for query in queries:
        log(f"  → {query}")
        try:
            results = search_web(query, max_results=5)
            for r in results:
                if r.url in seen_urls or not is_valid_source(r.url):
                    continue
                seen_urls.add(r.url)
                all_results.append(r)
            time.sleep(1)
        except Exception as e:
            log(f"  Search failed: {e}")

    sources = []
    for r in all_results:
        src_type = classify_source(r.url, r.title)
        sources.append(Source(title=r.title, url=r.url, type=src_type, snippet=r.snippet))

    log(f"Found {len(sources)} unique sources")
    if len(sources) < 2:
        log("Warning: Very few sources found. Research may be limited.")
    return sources


def fetch_sources(sources: List[Source]) -> List[Source]:
    """Fetch full text from the most promising sources."""
    log("Fetching source content...")
    prioritized = sorted(sources, key=lambda s: 0 if s.type == "primary" else 1)
    fetched = 0

    for source in prioritized:
        if fetched >= MAX_FETCHES:
            break
        log(f"  → {source.url[:70]}...")
        page = fetch_page(source.url)
        if page and page.text and len(page.text) > 200:
            text = page.text[:MAX_CONTENT_LENGTH]
            if len(page.text) > MAX_CONTENT_LENGTH:
                text += "\n...[truncated]"
            source.fetched_text = text
            source.title = page.title or source.title
            fetched += 1
            time.sleep(0.5)
        else:
            log("    No useful content.")

    log(f"Fetched content from {fetched} sources")
    return sources


def synthesize(llm, question: str, sources: List[Source]) -> ResearchReport:
    """Synthesize evidence into a structured report."""
    log("Synthesizing findings...")

    sources_text = []
    for i, s in enumerate(sources, 1):
        entry = f"Source {i}: {s.title} ({s.type})\nURL: {s.url}\n"
        if s.fetched_text:
            entry += f"Content: {s.fetched_text[:1200]}\n"
        elif s.snippet:
            entry += f"Snippet: {s.snippet}\n"
        sources_text.append(entry)

    prompt = SYNTHESIS_PROMPT.format(
        question=question,
        sources_text="\n---\n".join(sources_text)
    )
    messages = [
        {"role": "system", "content": STAR1_SYSTEM_PROMPT},
        {"role": "user", "content": prompt}
    ]
    response = call_llm(llm, messages, temperature=0.3, max_tokens=3000)
    data = parse_json(response)

    if not data:
        log("Could not parse structured report. Building fallback.")
        return build_fallback(question, sources, response)

    findings = []
    for f in data.get("key_findings", []):
        if isinstance(f, dict):
            findings.append(Finding(title=f.get("title", ""), content=f.get("content", "")))

    comparison = None
    comp = data.get("comparison")
    if comp and isinstance(comp, dict):
        comparison = Comparison(
            headers=comp.get("headers", []),
            rows=comp.get("rows", [])
        )

    report_sources = []
    for s in data.get("sources", []):
        if isinstance(s, dict):
            report_sources.append(Source(
                title=s.get("title", "Unknown"),
                url=s.get("url", ""),
                type=s.get("type", "secondary")
            ))

    if not report_sources:
        report_sources = [s for s in sources if s.url]

    return ResearchReport(
        title=data.get("title", "Research Report"),
        executive_summary=data.get("executive_summary", ""),
        key_findings=findings,
        comparison=comparison,
        evidence_assessment=data.get("evidence_assessment", ""),
        confidence_notes=data.get("confidence_notes", ""),
        sources=report_sources,
        question=question
    )


def build_fallback(question: str, sources: List[Source], raw: str) -> ResearchReport:
    """Build a basic report when JSON parsing fails."""
    return ResearchReport(
        title=f"Research: {question[:60]}",
        executive_summary="Star1 completed the research but encountered a formatting issue.",
        key_findings=[Finding(title="Analysis", content=raw[:2000])],
        evidence_assessment="See raw analysis above.",
        confidence_notes="Structured synthesis failed. Evidence was gathered but formatting encountered an error.",
        sources=[s for s in sources if s.url]
    )

# ─── Simple test mode ───

def simple_test(llm, question: str) -> str:
    """Run a simple chat completion to verify the model works."""
    log_section("Simple Test Mode")
    log("Asking the model a simple question to verify it loads and responds.")

    messages = [
        {"role": "system", "content": SIMPLE_TEST_PROMPT},
        {"role": "user", "content": question}
    ]
    response = call_llm(llm, messages, temperature=0.5, max_tokens=512)

    if not response:
        log_error("Model returned empty response")
        return ""

    log("Model responded successfully.")
    print(f"\n{'=' * 40}")
    print("RESPONSE:")
    print(f"{'=' * 40}")
    print(response)
    print(f"{'=' * 40}\n")
    return response

# ─── Main ───

def main():
    log_section("Star1 / Winery")
    log(f"Question: {RESEARCH_QUESTION or '(none provided)'}")
    log(f"Model: {MODEL_REPO}/{MODEL_FILE}")
    log(f"Threads: {N_THREADS} | Context: {N_CTX}")

    # Step 1: Ensure model exists
    model_path = ensure_model()

    # Step 2: Load model
    llm = load_llm(model_path)

    # If no question, just do a simple test
    if not RESEARCH_QUESTION:
        log("No RESEARCH_QUESTION set. Running simple test.")
        simple_test(llm, "Hello. Who are you and what can you do?")
        return

    # If question is very short or looks like a test, do simple mode
    if len(RESEARCH_QUESTION) < 20 or RESEARCH_QUESTION.lower() in ["test", "hello", "hi"]:
        simple_test(llm, RESEARCH_QUESTION)
        return

    # Full research pipeline
    job = ResearchJob(question=RESEARCH_QUESTION)

    try:
        log_section("Research Pipeline")

        # Plan
        job.status = "planning"
        plan = generate_plan(llm, RESEARCH_QUESTION)
        job.plan = plan

        # Search
        job.status = "researching"
        sources = execute_searches(plan)
        job.sources = sources

        # Fetch
        sources = fetch_sources(sources)
        job.sources = sources

        # Synthesize
        job.status = "synthesizing"
        report = synthesize(llm, RESEARCH_QUESTION, sources)

        # Output
        job.status = "complete"
        output = {
            "job": {
                "question": job.question,
                "plan": job.plan,
                "status": job.status,
                "sources_count": len(job.sources),
                "fetched_count": len([s for s in job.sources if s.fetched_text])
            },
            "report": report.to_dict()
        }

        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(output, f, indent=2, ensure_ascii=False)

        log_section("Research Complete")
        log(f"Result saved to: {RESULT_PATH}")
        log(f"Sources: {len(report.sources)} | Findings: {len(report.key_findings)}")
        print(f"\n--- EXECUTIVE SUMMARY ---")
        print(report.executive_summary)
        print(f"---\n")

    except Exception as e:
        job.status = "failed"
        job.error = str(e)
        log_error("Research pipeline failed", str(e))

        error_output = {
            "job": {
                "question": job.question,
                "status": "failed",
                "error": job.error
            },
            "report": None
        }
        with open(RESULT_PATH, "w", encoding="utf-8") as f:
            json.dump(error_output, f, indent=2)

        sys.exit(1)


if __name__ == "__main__":
    main()
