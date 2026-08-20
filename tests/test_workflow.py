"""Static analysis tests for the GitHub Actions workflow."""

import yaml
from pathlib import Path


class TestWorkflow:
    def test_workflow_file_is_valid_yaml(self):
        wf_path = Path(__file__).parent.parent / ".github" / "workflows" / "nanofossil.yml"
        assert wf_path.exists()
        with open(wf_path) as f:
            data = yaml.safe_load(f)
        assert data["name"] == "Nanofossil"

    def test_has_required_permissions(self):
        wf_path = Path(__file__).parent.parent / ".github" / "workflows" / "nanofossil.yml"
        with open(wf_path) as f:
            data = yaml.safe_load(f)
        assert data.get("permissions", {}).get("contents") == "write"

    def test_timeout_is_set(self):
        wf_path = Path(__file__).parent.parent / ".github" / "workflows" / "nanofossil.yml"
        with open(wf_path) as f:
            data = yaml.safe_load(f)
        assert data["jobs"]["run-star1"]["timeout-minutes"] <= 20

    def test_env_vars_defined(self):
        wf_path = Path(__file__).parent.parent / ".github" / "workflows" / "nanofossil.yml"
        with open(wf_path) as f:
            data = yaml.safe_load(f)
        env = data.get("env", {})
        assert "MODEL_REPO" in env
        assert "MODEL_FILE" in env
        assert "RESULT_PATH" in env
