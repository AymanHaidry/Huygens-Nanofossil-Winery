# Star1 — Research anything.

**Star1** is Huygens's autonomous research instrument.  
Give it a question. Let it investigate the evidence. Receive a carefully synthesized answer.

> The rabbit hole is yours.

---

## V3 Architecture

```
┌─────────────────┐     ┌─────────────────┐     ┌─────────────────┐
│   GitHub Pages  │────▶│  GitHub Actions │────▶│   Qwen3-4B GGUF │
│  (Star1 frontend)│     │   (Winery agent) │     │  (local inference)│
└─────────────────┘     └─────────────────┘     └─────────────────┘
                              │
                              ▼
                        DuckDuckGo search
                        Page fetching
                        Result commit
```

**₹0 cost.** No paid APIs. No permanent server.

---

## Quick Start

### 1. Create the repo

Push all files from this repo to a new GitHub repository.

### 2. Enable GitHub Pages

**Settings → Pages → Source:** Deploy from a branch → `main` → `/ (root)`

### 3. Enable Actions permissions

**Settings → Actions → General:**
- Actions permissions: "Allow all actions"
- Workflow permissions: "Read and write permissions"

### 4. Open Star1

Visit your GitHub Pages URL. Configure:
- **GitHub PAT:** Create at [github.com/settings/tokens/new](https://github.com/settings/tokens/new) with `repo` + `actions` scope
- **Repository:** `yourusername/star1`

### 5. Research

Type a question, hit enter, watch Star1 investigate.

---

## How it works

1. **Frontend** (GitHub Pages) captures your question and triggers `workflow_dispatch`
2. **GitHub Actions** spins up a runner, loads cached Qwen3-4B model
3. **Winery** plans searches → searches web → fetches sources → synthesizes report
4. **Result** committed to `results/{run_id}.json`
5. **Frontend** polls and displays the structured report

---

## File Structure

```
star1/
├── index.html              # Frontend landing + report view
├── assets/
│   ├── style.css           # Star1 design system
│   └── app.js              # Frontend logic, GitHub API, polling
├── winery/
│   ├── main.py             # Agent orchestration
│   ├── prompts.py          # System prompts for Qwen3-4B
│   ├── tools.py            # Search, fetch, classify
│   └── models.py           # Data models
├── .github/workflows/
│   └── star1.yml           # CI workflow
├── requirements.txt
└── README.md
```

---

## Backend Configuration

Set via workflow `env:` or repository variables:

| Variable | Default | Description |
|----------|---------|-------------|
| `MODEL_REPO` | `bartowski/Qwen_Qwen3-4B-GGUF` | Hugging Face repo |
| `MODEL_FILE` | `Qwen_Qwen3-4B-Q4_K_M.gguf` | GGUF filename |
| `N_CTX` | `8192` | Model context window |
| `N_THREADS` | `2` | CPU threads |
| `MAX_SEARCHES` | `6` | Search queries per research |
| `MAX_FETCHES` | `8` | Pages to fetch |
| `MAX_CONTENT_LENGTH` | `6000` | Chars per page for LLM |

---

## Troubleshooting

| Problem | Fix |
|---------|-----|
| Model 404 | Check `MODEL_REPO`/`MODEL_FILE` exist on HF. Try `unsloth/Qwen3-4B-GGUF` |
| OOM / load fail | Use smaller quant (Q4_0), reduce `N_CTX` to 4096 |
| No sources | DuckDuckGo rate limit. Retry later. |
| Push 403 | Check **Settings → Actions → Workflow permissions → Read and write** |
| Frontend blank | Check GitHub Pages is enabled and built from `main` root |

---

## Roadmap

- [ ] Test 8B model for better synthesis
- [ ] Add Brave Search / SerpAPI fallback
- [ ] PDF text extraction
- [ ] Scheduled research jobs
- [ ] Persistent memory across sessions

---

## License

Personal use only. Star1 is a Huygens product.
