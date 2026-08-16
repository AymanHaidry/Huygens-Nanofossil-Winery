# Star1 — Research anything.

**Star1** is Huygens's autonomous research instrument.  
Give it a question. Let it investigate the evidence. Receive a carefully synthesized answer.

> The rabbit hole is yours.

---

## V2 Architecture

```
GitHub Actions runner (ephemeral)
  ├── downloads Qwen3-4B-GGUF (cached)
  ├── loads it via llama-cpp-python
  ├── Winery agent orchestrates
  │   ├── plans searches
  │   ├── searches DuckDuckGo
  │   ├── fetches pages
  │   └── synthesizes via Qwen
  └── commits result to repo
```

**No paid APIs. No permanent server. ₹0 compute.**

---

## Setup

### 1. Create the repository

Push these files to a new GitHub repo:

```
star1/
├── winery/
│   ├── main.py
│   ├── prompts.py
│   ├── tools.py
│   └── models.py
├── requirements.txt
└── .github/
    └── workflows/
        └── star1.yml
```

### 2. Configure (optional)

The workflow defaults to:

| Setting | Default |
|---------|---------|
| Model repo | `Qwen/Qwen3-4B-GGUF` |
| Model file | `qwen3-4b-q4_k_m.gguf` |
| Context | 8192 tokens |
| Threads | 2 |

Override via repository variables or workflow env:

```yaml
env:
  MODEL_REPO: unsloth/Qwen3-4B-GGUF
  MODEL_FILE: qwen3-4b-q4_k_m.gguf
  N_CTX: 8192
  N_THREADS: 2
```

### 3. First test

**GitHub → Actions → Star1 → Run workflow**

Leave the question field empty or enter `test`.

This verifies:
- Model downloads correctly
- Model loads in the runner
- Model responds to a simple prompt

### 4. Run research

**GitHub → Actions → Star1 → Run workflow**

Enter a research question, e.g.:

> Why did Concorde fail commercially?

The runner will:
1. Load the cached model (or download it)
2. Plan search queries
3. Search the web
4. Fetch source pages
5. Synthesize a structured report
6. Commit `results/{run_id}.json`

---

## How it works

### Model caching

The workflow uses `actions/cache` on the `models/` directory. After the first run, the model is cached and subsequent runs skip the download.

Cache key: `ubuntu-star1-model-{repo}-{file}`

If you change the model, the cache key changes and it re-downloads.

### Model size

Qwen3-4B Q4_K_M is approximately **2.3 GB**. It fits comfortably in a GitHub Actions free runner (7 GB RAM, 14 GB SSD).

If you want to test a different quantization:

| Quant | Size | Speed | Quality |
|-------|------|-------|---------|
| Q4_0 | ~1.9 GB | Fastest | Baseline |
| Q4_K_M | ~2.3 GB | Fast | Good |
| Q5_K_M | ~2.8 GB | Moderate | Better |
| Q6_K | ~3.3 GB | Slower | Best |

### Research pipeline

```
Question
  ↓
Plan (3-5 search queries)
  ↓
Search DuckDuckGo
  ↓
Fetch top sources
  ↓
Synthesize with Qwen
  ↓
Structured JSON report
```

The report includes:
- Executive summary
- Key findings
- Evidence assessment
- Confidence notes
- Sources (primary vs secondary)

---

## Troubleshooting

### Model download fails

```
[Winery] ERROR: Failed to download model
```

- Check that `MODEL_REPO` and `MODEL_FILE` exist on Hugging Face.
- If the model is gated, add `HF_TOKEN` to GitHub Secrets.
- Try a different repo like `unsloth/Qwen3-4B-GGUF` or `bartowski/Qwen3-4B-GGUF`.

### Model load fails / OOM

```
[Winery] ERROR: Failed to load model
```

- The runner may not have enough RAM. Try a smaller quantization (Q4_0).
- Reduce `N_CTX` to 4096.

### Empty or garbled response

- Qwen3 sometimes outputs `think` tags. Winery strips them automatically.
- If responses are nonsense, the model file may be corrupt. Clear the cache and re-download.

### No sources found

```
[Winery] Warning: Very few sources found.
```

- DuckDuckGo may be rate-limiting. The runner IP might be blocked.
- Try running again later, or test locally first.

---

## Local testing

```bash
# Install dependencies
pip install -r requirements.txt

# Download model
python -c "
from huggingface_hub import hf_hub_download
hf_hub_download(
    repo_id='Qwen/Qwen3-4B-GGUF',
    filename='qwen3-4b-q4_k_m.gguf',
    local_dir='models/',
    local_dir_use_symlinks=False
)
"

# Simple test
RESEARCH_QUESTION="test" python winery/main.py

# Full research
RESEARCH_QUESTION="Why did Concorde fail commercially?" python winery/main.py
```

---

## V2 Limitations

- 4B model is less capable than Kimi K3. Synthesis quality is lower.
- No real-time progress updates (GitHub Actions is batch).
- PDF text extraction not supported.
- Research limited to ~15 minutes per run.
- DuckDuckGo search can be unreliable from cloud IPs.

---

## Roadmap

- [ ] Test 8B quantized model for better synthesis
- [ ] Add Brave Search or SerpAPI as fallback
- [ ] PDF text extraction
- [ ] Persistent memory / research history
- [ ] Scheduled research jobs
- [ ] Frontend (V3)

---

## License

Personal use only. Star1 is a Huygens product.
