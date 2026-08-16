/* ─── Star1 Frontend ─── */

const CONFIG = {
    pollInterval: 10000,
    maxPolls: 90,
    githubApi: 'https://api.github.com'
};

let currentJob = null;
let pollTimer = null;
let pollCount = 0;

// ─── State Management ───

function showState(stateId) {
    document.querySelectorAll('.state').forEach(s => s.classList.remove('active'));
    document.getElementById(stateId).classList.add('active');
}

function getSettings() {
    return {
        pat: localStorage.getItem('star1_pat') || '',
        repo: localStorage.getItem('star1_repo') || ''
    };
}

function saveSettings(pat, repo) {
    localStorage.setItem('star1_pat', pat);
    localStorage.setItem('star1_repo', repo);
}

// ─── GitHub API ───

async function githubRequest(endpoint, options = {}) {
    const { pat } = getSettings();
    const url = `${CONFIG.githubApi}${endpoint}`;

    const res = await fetch(url, {
        ...options,
        headers: {
            'Accept': 'application/vnd.github+json',
            'Authorization': `Bearer ${pat}`,
            'X-GitHub-Api-Version': '2022-11-28',
            ...options.headers
        }
    });

    if (!res.ok) {
        const err = await res.json().catch(() => ({}));
        throw new Error(err.message || `GitHub API error: ${res.status}`);
    }

    return res.json();
}

async function triggerResearch(question) {
    const { repo } = getSettings();
    const [owner, repoName] = repo.split('/');

    await githubRequest(`/repos/${owner}/${repoName}/actions/workflows/star1.yml/dispatches`, {
        method: 'POST',
        body: JSON.stringify({ ref: 'main', inputs: { question } })
    });

    await new Promise(r => setTimeout(r, 4000));

    const runs = await githubRequest(`/repos/${owner}/${repoName}/actions/runs?event=workflow_dispatch&per_page=5`);
    const run = runs.workflow_runs.find(r =>
        r.name === 'Star1' &&
        r.status !== 'completed'
    );

    if (!run) {
        return { id: `job-${Date.now()}`, runId: null };
    }

    return { id: run.id.toString(), runId: run.id };
}

async function checkJobStatus(runId) {
    const { repo } = getSettings();
    const [owner, repoName] = repo.split('/');

    const run = await githubRequest(`/repos/${owner}/${repoName}/actions/runs/${runId}`);

    if (run.status === 'completed') {
        if (run.conclusion === 'success') {
            try {
                const content = await githubRequest(`/repos/${owner}/${repoName}/contents/results/${runId}.json`);
                const decoded = JSON.parse(atob(content.content));
                return { status: 'success', result: decoded };
            } catch (e) {
                return { status: 'success', result: null };
            }
        } else {
            return { status: 'failed', error: `Research job failed: ${run.conclusion}` };
        }
    }

    return { status: 'running', runStatus: run.status };
}

async function fetchRecentResearch() {
    const { repo } = getSettings();
    if (!repo) return [];

    const [owner, repoName] = repo.split('/');
    try {
        const contents = await githubRequest(`/repos/${owner}/${repoName}/contents/results?per_page=10`);
        if (!Array.isArray(contents)) return [];

        const items = [];
        for (const file of contents.reverse().slice(0, 8)) {
            if (!file.name.endsWith('.json')) continue;
            try {
                const content = await githubRequest(`/repos/${owner}/${repoName}/contents/results/${file.name}`);
                const decoded = JSON.parse(atob(content.content));
                items.push({
                    runId: file.name.replace('.json', ''),
                    question: decoded.job?.question || 'Unknown question',
                    status: decoded.job?.status || 'unknown',
                    date: new Date(decoded.report?.generated_at || content.sha).toLocaleDateString(),
                    title: decoded.report?.title || 'Research Report'
                });
            } catch (e) {
                // Skip malformed files
            }
        }
        return items;
    } catch (e) {
        return [];
    }
}

// ─── UI Updates ───

function setStepState(stepName, state) {
    const step = document.querySelector(`[data-step="${stepName}"]`);
    if (!step) return;
    step.classList.remove('pending', 'active', 'done');
    step.classList.add(state);
}

function updateProgress(runStatus) {
    const steps = ['understand', 'research', 'crosscheck', 'synthesize', 'write'];

    if (runStatus === 'queued' || runStatus === 'waiting') {
        setStepState('understand', 'active');
    } else if (runStatus === 'in_progress') {
        const elapsed = pollCount * CONFIG.pollInterval / 1000;
        if (elapsed < 20) {
            setStepState('understand', 'done');
            setStepState('research', 'active');
        } else if (elapsed < 60) {
            setStepState('understand', 'done');
            setStepState('research', 'done');
            setStepState('crosscheck', 'active');
        } else if (elapsed < 100) {
            setStepState('understand', 'done');
            setStepState('research', 'done');
            setStepState('crosscheck', 'done');
            setStepState('synthesize', 'active');
        } else {
            setStepState('understand', 'done');
            setStepState('research', 'done');
            setStepState('crosscheck', 'done');
            setStepState('synthesize', 'done');
            setStepState('write', 'active');
        }
    }
}

function resetProgress() {
    ['understand', 'research', 'crosscheck', 'synthesize', 'write'].forEach(step => {
        setStepState(step, 'pending');
    });
}

async function renderRecentResearch() {
    const container = document.getElementById('recent-list');
    const items = await fetchRecentResearch();

    if (items.length === 0) {
        container.innerHTML = '<p class="recent-empty">No research yet. Ask something above.</p>';
        return;
    }

    container.innerHTML = items.map(item => `
        <button class="recent-item" data-run-id="${item.runId}">
            <span class="recent-item-status ${item.status}"></span>
            <div class="recent-item-text">
                <div class="recent-item-question">${escapeHtml(item.question)}</div>
                <div class="recent-item-meta">${escapeHtml(item.title)} · ${item.date}</div>
            </div>
            <svg class="recent-item-arrow" width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                <polyline points="9 18 15 12 9 6"/>
            </svg>
        </button>
    `).join('');

    container.querySelectorAll('.recent-item').forEach(btn => {
        btn.addEventListener('click', () => loadPastResearch(btn.dataset.runId));
    });
}

async function loadPastResearch(runId) {
    const { repo } = getSettings();
    const [owner, repoName] = repo.split('/');

    try {
        const content = await githubRequest(`/repos/${owner}/${repoName}/contents/results/${runId}.json`);
        const decoded = JSON.parse(atob(content.content));
        if (decoded.report) {
            renderReport(decoded);
            showState('report');
        }
    } catch (e) {
        alert('Could not load this research result.');
    }
}

// ─── Report Rendering ───

function renderReport(data) {
    const container = document.getElementById('report-content');

    if (!data || !data.report) {
        container.innerHTML = `
            <div class="error-banner">
                <h3>Star1 couldn't complete the research.</h3>
                <p>The result file was empty or malformed.</p>
                <button class="retry-btn" onclick="location.reload()">Try again</button>
                <button class="change-btn" onclick="showState('landing')">Change the question</button>
            </div>
        `;
        return;
    }

    const r = data.report;
    const date = r.generated_at
        ? new Date(r.generated_at).toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' })
        : new Date().toLocaleDateString('en-US', { year: 'numeric', month: 'long', day: 'numeric' });

    let html = `
        <h1 class="report-title">${escapeHtml(r.title || 'Research Report')}</h1>
        <div class="report-meta">
            <span>Star1</span>
            <span>·</span>
            <span>${date}</span>
            <span>·</span>
            <span>${r.sources ? r.sources.length : 0} sources</span>
        </div>
    `;

    if (r.executive_summary) {
        html += `
            <div class="executive-summary">
                <h2>Executive summary</h2>
                <p>${escapeHtml(r.executive_summary)}</p>
            </div>
        `;
    }

    if (r.key_findings && r.key_findings.length > 0) {
        html += `<h2 class="section-heading">Key findings</h2><ol class="findings-list">`;
        r.key_findings.forEach((finding, i) => {
            html += `
                <li class="finding-item">
                    <h3><span class="finding-number">${String(i + 1).padStart(2, '0')}</span> ${escapeHtml(finding.title)}</h3>
                    <p>${escapeHtml(finding.content)}</p>
                </li>
            `;
        });
        html += `</ol>`;
    }

    if (r.comparison && r.comparison.headers && r.comparison.rows) {
        html += `<h2 class="section-heading">Comparison</h2>`;
        html += `<table class="comparison-table"><thead><tr>`;
        r.comparison.headers.forEach(h => {
            html += `<th>${escapeHtml(h)}</th>`;
        });
        html += `</tr></thead><tbody>`;
        r.comparison.rows.forEach(row => {
            html += `<tr>`;
            row.forEach(cell => {
                html += `<td>${escapeHtml(cell)}</td>`;
            });
            html += `</tr>`;
        });
        html += `</tbody></table>`;
    }

    if (r.evidence_assessment) {
        html += `
            <div class="evidence-section">
                <h3>What the evidence suggests</h3>
                <p>${escapeHtml(r.evidence_assessment)}</p>
            </div>
        `;
    }

    if (r.confidence_notes) {
        html += `
            <div class="confidence-note">
                <svg class="confidence-icon" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                    <circle cx="12" cy="12" r="10"/>
                    <line x1="12" y1="16" x2="12" y2="12"/>
                    <line x1="12" y1="8" x2="12.01" y2="8"/>
                </svg>
                <p>${escapeHtml(r.confidence_notes)}</p>
            </div>
        `;
    }

    if (r.sources && r.sources.length > 0) {
        const primaryCount = r.sources.filter(s => s.type === 'primary').length;
        const secondaryCount = r.sources.filter(s => s.type === 'secondary').length;

        html += `
            <div class="sources-section">
                <button class="sources-toggle" onclick="this.nextElementSibling.classList.toggle('open')">
                    Sources
                    <span class="sources-count">${r.sources.length} · ${primaryCount} primary · ${secondaryCount} secondary</span>
                    <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round">
                        <polyline points="6 9 12 15 18 9"/>
                    </svg>
                </button>
                <ol class="sources-list">
        `;

        r.sources.forEach((source, i) => {
            html += `
                <li class="source-item">
                    <span class="source-number">${i + 1}</span>
                    <div class="source-content">
                        <div class="source-title">${escapeHtml(source.title)}</div>
                        <a href="${escapeHtml(source.url)}" target="_blank" rel="noopener" class="source-url">${escapeHtml(source.url)}</a>
                        <span class="source-type ${source.type || 'secondary'}">${source.type || 'secondary'}</span>
                    </div>
                </li>
            `;
        });

        html += `</ol></div>`;
    }

    container.innerHTML = html;
}

function escapeHtml(text) {
    if (!text) return '';
    const div = document.createElement('div');
    div.textContent = text;
    return div.innerHTML;
}

// ─── Polling ───

async function pollJob() {
    if (!currentJob || !currentJob.runId) return;

    pollCount++;

    if (pollCount > CONFIG.maxPolls) {
        clearInterval(pollTimer);
        showError('Research is taking longer than expected. You can check the GitHub Actions tab for status.');
        return;
    }

    try {
        const status = await checkJobStatus(currentJob.runId);

        if (status.status === 'running') {
            updateProgress(status.runStatus);
        } else if (status.status === 'success') {
            clearInterval(pollTimer);
            setStepState('write', 'done');

            if (status.result) {
                renderReport(status.result);
                showState('report');
                renderRecentResearch();
            } else {
                showError('Research completed but no result was found. The result file may still be processing.');
            }
        } else if (status.status === 'failed') {
            clearInterval(pollTimer);
            showError(status.error || 'Star1 couldn't complete the research.');
        }
    } catch (err) {
        console.error('Poll error:', err);
    }
}

function showError(message) {
    const container = document.getElementById('report-content');
    container.innerHTML = `
        <div class="error-banner">
            <h3>Star1 couldn't complete the research.</h3>
            <p>${escapeHtml(message)}</p>
            <button class="retry-btn" onclick="location.reload()">Try again</button>
            <button class="change-btn" onclick="showState('landing')">Change the question</button>
        </div>
    `;
    showState('report');
}

// ─── Event Handlers ───

async function startResearch(question) {
    const settings = getSettings();

    if (!settings.pat || !settings.repo) {
        document.getElementById('settings-modal').classList.add('open');
        return;
    }

    document.getElementById('active-question').textContent = question;
    document.getElementById('job-id-display').textContent = 'Triggering...';
    resetProgress();
    showState('researching');

    try {
        const job = await triggerResearch(question);
        currentJob = job;
        document.getElementById('job-id-display').textContent = `Job #${job.id}`;

        if (job.runId) {
            pollCount = 0;
            pollTimer = setInterval(pollJob, CONFIG.pollInterval);
            pollJob();
        } else {
            setTimeout(async () => {
                const { repo } = getSettings();
                const [owner, repoName] = repo.split('/');
                const runs = await githubRequest(`/repos/${owner}/${repoName}/actions/runs?event=workflow_dispatch&per_page=5`);
                const run = runs.workflow_runs.find(r => r.name === 'Star1' && r.status !== 'completed');
                if (run) {
                    currentJob = { id: run.id.toString(), runId: run.id };
                    document.getElementById('job-id-display').textContent = `Job #${run.id}`;
                    pollCount = 0;
                    pollTimer = setInterval(pollJob, CONFIG.pollInterval);
                    pollJob();
                }
            }, 6000);
        }
    } catch (err) {
        console.error('Start research error:', err);
        showError(err.message || 'Failed to start research. Check your GitHub token and repository settings.');
    }
}

// ─── Test Connection ───

async function testConnection() {
    const resultEl = document.getElementById('test-result');
    const pat = document.getElementById('github-pat').value.trim();
    const repo = document.getElementById('github-repo').value.trim();

    if (!pat || !repo) {
        resultEl.textContent = 'Please fill in both fields.';
        resultEl.className = 'test-result error';
        return;
    }

    resultEl.textContent = 'Testing...';
    resultEl.className = 'test-result';

    try {
        const [owner, repoName] = repo.split('/');
        await fetch(`${CONFIG.githubApi}/repos/${owner}/${repoName}`, {
            headers: {
                'Authorization': `Bearer ${pat}`,
                'Accept': 'application/vnd.github+json'
            }
        });

        // Also test workflow access
        await fetch(`${CONFIG.githubApi}/repos/${owner}/${repoName}/actions/workflows/star1.yml`, {
            headers: {
                'Authorization': `Bearer ${pat}`,
                'Accept': 'application/vnd.github+json'
            }
        });

        resultEl.textContent = 'Connection successful. Star1 is ready.';
        resultEl.className = 'test-result success';
    } catch (e) {
        resultEl.textContent = `Connection failed: ${e.message}`;
        resultEl.className = 'test-result error';
    }
}

// ─── Init ───

document.addEventListener('DOMContentLoaded', () => {
    const settings = getSettings();
    if (!settings.pat || !settings.repo) {
        document.getElementById('settings-modal').classList.add('open');
    } else {
        renderRecentResearch();
    }

    // Pre-fill settings if they exist
    if (settings.pat) document.getElementById('github-pat').value = settings.pat;
    if (settings.repo) document.getElementById('github-repo').value = settings.repo;

    // Submit research
    const input = document.getElementById('research-question');
    const submitBtn = document.getElementById('submit-research');

    function handleSubmit() {
        const question = input.value.trim();
        if (!question) return;
        startResearch(question);
    }

    submitBtn.addEventListener('click', handleSubmit);
    input.addEventListener('keypress', (e) => {
        if (e.key === 'Enter') handleSubmit();
    });

    // Example chips
    document.querySelectorAll('.example-chip').forEach(chip => {
        chip.addEventListener('click', () => {
            input.value = chip.dataset.question;
            handleSubmit();
        });
    });

    // Cancel
    document.getElementById('cancel-research').addEventListener('click', () => {
        if (pollTimer) clearInterval(pollTimer);
        currentJob = null;
        showState('landing');
    });

    // New research
    document.getElementById('new-research').addEventListener('click', () => {
        input.value = '';
        showState('landing');
    });

    // Open settings
    document.getElementById('open-settings').addEventListener('click', () => {
        document.getElementById('settings-modal').classList.add('open');
    });

    // Save settings
    document.getElementById('save-settings').addEventListener('click', () => {
        const pat = document.getElementById('github-pat').value.trim();
        const repo = document.getElementById('github-repo').value.trim();

        if (!pat || !repo) {
            alert('Both fields are required.');
            return;
        }

        saveSettings(pat, repo);
        document.getElementById('settings-modal').classList.remove('open');
        renderRecentResearch();
    });

    // Test connection
    document.getElementById('test-connection').addEventListener('click', testConnection);

    // Close modal on backdrop click
    document.querySelector('.modal-backdrop').addEventListener('click', () => {
        document.getElementById('settings-modal').classList.remove('open');
    });
});
