"""Tests for custom semgrep rules.

Validates that:
1. All rule files are valid YAML
2. All rules have required semgrep structure
3. Rules can be loaded by semgrep (if installed)
4. Rule IDs are unique across files
5. Live scans against argus_mcp/ produce zero findings
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

try:
    import yaml

    HAS_YAML = True
except ImportError:
    HAS_YAML = False

RULES_DIR = Path(__file__).parent.parent / "internal" / "rules"
SOURCE_DIR = Path(__file__).parent.parent / "argus_mcp"
HAS_SEMGREP = shutil.which("semgrep") is not None

pytestmark = pytest.mark.semgrep


# Files that are YAML but not semgrep rule files.
_NON_RULE_FILES = {"docker-compose.yml", "docker-compose.yaml"}


def _get_rule_files() -> list[Path]:
    """Get all .yml/.yaml rule files from the rules directory."""
    if not RULES_DIR.exists():
        return []
    return sorted(
        p
        for p in RULES_DIR.iterdir()
        if p.suffix in (".yml", ".yaml") and p.is_file() and p.name not in _NON_RULE_FILES
    )


class TestRuleFilesExist:
    def test_rules_directory_exists(self) -> None:
        assert RULES_DIR.exists(), f"Rules directory not found: {RULES_DIR}"

    def test_has_rule_files(self) -> None:
        files = _get_rule_files()
        assert len(files) > 0, "Expected at least one rule file"

    def test_expected_rule_files(self) -> None:
        """Verify known rule files are present."""
        expected_names = {
            "agent-runtime",
            "architecture",
            "asyncio",
            "code-quality",
            "dependency-hygiene",
            "docker",
            "httpx",
            "security",
            "starlette",
            "textual",
        }
        actual_names = {p.stem for p in _get_rule_files()}
        missing = expected_names - actual_names
        assert not missing, f"Missing rule files: {missing}"


@pytest.mark.skipif(not HAS_YAML, reason="pyyaml not installed")
class TestRuleFileStructure:
    """Validate YAML structure of each rule file."""

    @pytest.fixture(params=_get_rule_files(), ids=lambda p: p.stem)
    def rule_file(self, request) -> Path:
        return request.param

    def test_valid_yaml(self, rule_file: Path) -> None:
        with open(rule_file) as f:
            data = yaml.safe_load(f)
        assert data is not None, f"{rule_file.name} loaded as None"

    def test_has_rules_key(self, rule_file: Path) -> None:
        with open(rule_file) as f:
            data = yaml.safe_load(f)
        assert "rules" in data, f"{rule_file.name}: missing 'rules' key"

    def test_rules_is_list(self, rule_file: Path) -> None:
        with open(rule_file) as f:
            data = yaml.safe_load(f)
        assert isinstance(data["rules"], list), f"{rule_file.name}: 'rules' is not a list"

    def test_each_rule_has_required_fields(self, rule_file: Path) -> None:
        with open(rule_file) as f:
            data = yaml.safe_load(f)
        for i, rule in enumerate(data["rules"]):
            assert "id" in rule, f"{rule_file.name}[{i}]: missing 'id'"
            assert "message" in rule, f"{rule_file.name}[{i}]: missing 'message'"
            assert "severity" in rule, f"{rule_file.name}[{i}]: missing 'severity'"

    def test_valid_severity_levels(self, rule_file: Path) -> None:
        with open(rule_file) as f:
            data = yaml.safe_load(f)
        valid_severities = {"ERROR", "WARNING", "INFO"}
        for rule in data["rules"]:
            sev = rule.get("severity", "").upper()
            assert sev in valid_severities, (
                f"{rule_file.name}/{rule['id']}: invalid severity '{sev}'"
            )

    def test_each_rule_has_pattern(self, rule_file: Path) -> None:
        """Each rule must have a pattern, patterns, pattern-either, or pattern-sources."""
        with open(rule_file) as f:
            data = yaml.safe_load(f)
        pattern_keys = {
            "pattern",
            "patterns",
            "pattern-either",
            "pattern-regex",
            "pattern-sources",
            "pattern-sinks",
        }
        for rule in data["rules"]:
            has_pattern = bool(pattern_keys & set(rule.keys()))
            assert has_pattern, f"{rule_file.name}/{rule['id']}: missing pattern specification"


@pytest.mark.skipif(not HAS_YAML, reason="pyyaml not installed")
class TestRuleIDUniqueness:
    def test_all_rule_ids_unique(self) -> None:
        """Rule IDs must be unique across all files."""
        seen: dict[str, str] = {}
        for rule_file in _get_rule_files():
            with open(rule_file) as f:
                data = yaml.safe_load(f)
            for rule in data.get("rules", []):
                rid = rule.get("id", "")
                if rid in seen:
                    pytest.fail(
                        f"Duplicate rule ID '{rid}': found in {seen[rid]} and {rule_file.name}"
                    )
                seen[rid] = rule_file.name


@pytest.mark.skipif(not HAS_YAML, reason="pyyaml not installed")
class TestRuleLanguages:
    """Verify rules target appropriate languages."""

    def test_python_rules_target_python(self) -> None:
        """Rules in files likely targeting Python should have python language."""
        python_files = {"asyncio", "httpx", "starlette", "textual"}
        for rule_file in _get_rule_files():
            if rule_file.stem not in python_files:
                continue
            with open(rule_file) as f:
                data = yaml.safe_load(f)
            for rule in data.get("rules", []):
                langs = rule.get("languages", [])
                assert "python" in langs, (
                    f"{rule_file.name}/{rule['id']}: expected 'python' in languages, got {langs}"
                )

    def test_docker_rules_target_dockerfile(self) -> None:
        for rule_file in _get_rule_files():
            if rule_file.stem != "docker":
                continue
            with open(rule_file) as f:
                data = yaml.safe_load(f)
            for rule in data.get("rules", []):
                langs = rule.get("languages", [])
                assert any("docker" in lang.lower() for lang in langs), (
                    f"{rule_file.name}/{rule['id']}: expected dockerfile language"
                )


def _scannable_rule_files() -> list[Path]:
    """Rule files that target Python and can scan argus_mcp/."""
    if not HAS_YAML:
        return []
    python_targeting = set()
    for p in _get_rule_files():
        with open(p) as f:
            data = yaml.safe_load(f)
        for rule in data.get("rules", []):
            langs = rule.get("languages", [])
            if "python" in langs:
                python_targeting.add(p)
                break
    return sorted(python_targeting)


@pytest.mark.skipif(not HAS_SEMGREP, reason="semgrep CLI not installed")
@pytest.mark.skipif(not HAS_YAML, reason="pyyaml not installed")
class TestSemgrepLiveScan:
    """Run each Python-targeting rule file against argus_mcp/ and assert zero findings."""

    @pytest.fixture(params=_scannable_rule_files(), ids=lambda p: p.stem)
    def rule_file(self, request) -> Path:
        return request.param

    @pytest.mark.timeout(180)
    def test_zero_findings(self, rule_file: Path) -> None:
        """Semgrep scan with this rule file must produce no findings."""
        result = subprocess.run(
            [
                "semgrep",
                "--config",
                str(rule_file),
                str(SOURCE_DIR),
                "--json",
                "--quiet",
                "-j",
                "1",
                "--max-memory",
                "4096",
            ],
            capture_output=True,
            text=True,
            timeout=180,
            env={**os.environ, "SEMGREP_SEND_METRICS": "off"},
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            # If semgrep failed to produce JSON, check exit code
            assert result.returncode == 0, (
                f"semgrep exited {result.returncode} for {rule_file.name}:\n{result.stderr}"
            )
            return

        findings = data.get("results", [])
        if findings:
            details = "\n".join(
                f"  {f['check_id']} @ {f['path']}:{f['start']['line']}" for f in findings[:10]
            )
            pytest.fail(f"{rule_file.name}: {len(findings)} finding(s):\n{details}")


@pytest.mark.skipif(not HAS_SEMGREP, reason="semgrep CLI not installed")
class TestSemgrepDockerRuleScan:
    """Run Docker rules against the Dockerfile."""

    def test_dockerfile_clean(self) -> None:
        dockerfile = Path(__file__).parent.parent / "Dockerfile"
        docker_rules = RULES_DIR / "docker.yml"
        if not dockerfile.exists() or not docker_rules.exists():
            pytest.skip("Dockerfile or docker.yml not found")

        result = subprocess.run(
            [
                "semgrep",
                "--config",
                str(docker_rules),
                str(dockerfile),
                "--json",
                "--quiet",
                "-j",
                "1",
                "--max-memory",
                "2048",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "SEMGREP_SEND_METRICS": "off"},
        )
        try:
            data = json.loads(result.stdout)
        except json.JSONDecodeError:
            assert result.returncode == 0, f"semgrep exited {result.returncode}:\n{result.stderr}"
            return
        findings = data.get("results", [])
        if findings:
            details = "\n".join(
                f"  {f['check_id']} @ {f['path']}:{f['start']['line']}" for f in findings
            )
            pytest.fail(f"Dockerfile: {len(findings)} finding(s):\n{details}")


@pytest.mark.skipif(not HAS_SEMGREP, reason="semgrep CLI not installed")
class TestSemgrepRuleValidation:
    """Verify semgrep itself can validate/load each rule file."""

    @pytest.fixture(params=_get_rule_files(), ids=lambda p: p.stem)
    def rule_file(self, request) -> Path:
        return request.param

    @pytest.mark.xfail(
        reason="semgrep v1.153.1 --validate crashes with engine OOM (known bug)",
        strict=False,
    )
    def test_semgrep_validates_rule(self, rule_file: Path) -> None:
        """semgrep --validate must pass for each rule file."""
        result = subprocess.run(
            [
                "semgrep",
                "--validate",
                "--config",
                str(rule_file),
                "-j",
                "1",
                "--max-memory",
                "2048",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            env={**os.environ, "SEMGREP_SEND_METRICS": "off"},
        )
        assert result.returncode == 0, f"Validation failed for {rule_file.name}:\n{result.stderr}"
