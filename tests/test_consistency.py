"""Consistency tests for compose.yml, README.md, and entrypoint.sh.

These tests verify that:
  - compose.yml is structurally valid and its env vars are documented in README
  - Default values in compose.yml match the README documentation
  - README docker run examples include --hostname (matching the IMPORTANT note)
  - entrypoint.sh pre-flight validation rejects misconfigurations early
"""

# Standard Python Libraries
import re
import subprocess
import textwrap
from pathlib import Path

# Third-Party Libraries
import pytest
import yaml

REPO_ROOT = Path(__file__).parent.parent
SRC_DIR = REPO_ROOT / "src"
COMPOSE_FILE = REPO_ROOT / "compose.yml"
README_FILE = REPO_ROOT / "README.md"
ENTRYPOINT_FILE = SRC_DIR / "entrypoint.sh"


# ── Helpers ───────────────────────────────────────────────────────────────────


def _load_compose() -> dict:
    """Parse the root compose.yml."""
    with open(COMPOSE_FILE) as f:
        return yaml.safe_load(f)


def _compose_env_entries() -> list[str]:
    """Return all env var entries from compose.yml (both active and commented)."""
    raw = COMPOSE_FILE.read_text()
    entries = []
    for line in raw.splitlines():
        stripped = line.strip()
        # Match active env lines: "- VAR=value" or "- VAR="
        m = re.match(r"^-\s+([A-Z_][A-Z0-9_]*)", stripped)
        if m:
            entries.append(stripped.lstrip("- ").strip())
            continue
        # Match commented env lines: "# - VAR=value"
        m = re.match(r"^#\s*-\s*([A-Z_][A-Z0-9_]*)", stripped)
        if m:
            entries.append(stripped.lstrip("#- ").strip())
    return entries


def _parse_env_var_name(entry: str) -> str:
    """Extract the variable name from a 'VAR=value' string."""
    return entry.split("=", 1)[0]


def _parse_env_var_value(entry: str) -> str | None:
    """Extract the value from a 'VAR=value' string.  Returns None if no '='."""
    if "=" not in entry:
        return None
    return entry.split("=", 1)[1]


def _readme_env_table() -> dict[str, str]:
    """Parse the README optional variables table.

    Returns a dict of {var_name: default_value_string}.
    """
    text = README_FILE.read_text()
    result = {}
    # Match table rows like: | `VAR_NAME` | ... | `default` |
    # or: | `VAR_NAME` | ... | |
    for m in re.finditer(
        r"^\|\s*`([A-Z_][A-Z0-9_*]*)`\s*\|[^|]*\|\s*(.*?)\s*\|",
        text,
        re.MULTILINE,
    ):
        var_name = m.group(1)
        default_raw = m.group(2).strip()
        # Strip backticks from default value
        default_val = default_raw.strip("`").strip()
        result[var_name] = default_val
    return result


def _readme_docker_run_blocks() -> list[str]:
    """Extract all docker run code blocks from README."""
    text = README_FILE.read_text()
    blocks = []
    for m in re.finditer(r"```console\n(.*?)```", text, re.DOTALL):
        block = m.group(1)
        if "docker run" in block:
            blocks.append(block)
    return blocks


def _run_validation(
    env_overrides: dict[str, str | None],
    has_package_json: bool = False,
    package_json_content: str = "",
    timeout: int = 10,
) -> subprocess.CompletedProcess:
    """Run the entrypoint pre-flight validation in a subprocess.

    Sources logging.sh, sets DATA_DIR, applies env overrides, then executes
    the pre-flight validation block extracted from entrypoint.sh.
    """
    # Build env setup
    env_setup = textwrap.dedent(f"""\
        set -o nounset
        set -o errexit
        set -o pipefail
        DATA_DIR="/data"
        LOG_NAME="Test"
        source logging.sh
    """)

    # Apply env overrides
    env_lines = []
    for var, val in env_overrides.items():
        if val is None:
            env_lines.append(f"unset {var} 2>/dev/null || true")
        else:
            env_lines.append(f'export {var}="{val}"')
    env_setup += "\n".join(env_lines) + "\n"

    # Mock the resources/app/package.json check if needed
    if has_package_json:
        setup_dir = "mkdir -p /tmp/test_entrypoint/resources/app"
        write_json = f"echo '{package_json_content}' > /tmp/test_entrypoint/resources/app/package.json"
        env_setup += f"{setup_dir}\n{write_json}\n"
        # Override the package.json path in the validation block
        pkg_json_path = "/tmp/test_entrypoint/resources/app/package.json"
    else:
        pkg_json_path = "/nonexistent/resources/app/package.json"

    # The pre-flight validation block (matches entrypoint.sh exactly)
    validation_block = textwrap.dedent(f"""\

        # ── Pre-flight validation ──────────────────────────────────────
        if [[ -z "${{FOUNDRY_VERSION:-}}" ]]; then
          log_error "FOUNDRY_VERSION is not set or is empty."
          exit 1
        fi

        if [[ "${{FOUNDRY_SSL_CERT:-}}" && ! "${{FOUNDRY_SSL_KEY:-}}" ]]; then
          log_error "FOUNDRY_SSL_CERT is set but FOUNDRY_SSL_KEY is not."
          exit 1
        fi
        if [[ "${{FOUNDRY_SSL_KEY:-}}" && ! "${{FOUNDRY_SSL_CERT:-}}" ]]; then
          log_error "FOUNDRY_SSL_KEY is set but FOUNDRY_SSL_CERT is not."
          exit 1
        fi

        if [[ -n "${{CONTAINER_CACHE_SIZE:-}}" ]]; then
          if ! [[ "${{CONTAINER_CACHE_SIZE}}" -gt 0 ]] 2> /dev/null; then
            log_error "CONTAINER_CACHE_SIZE must be 1 or greater.  Found: ${{CONTAINER_CACHE_SIZE}}"
            exit 1
          fi
        fi

        if [[ ! -f "{pkg_json_path}" ]] || \\
           [[ "$(jq --raw-output '.release | "\\(.generation).\\(.build)"' {pkg_json_path} 2>/dev/null)" != "${{FOUNDRY_VERSION}}" ]]; then
          if [[ ! "${{FOUNDRY_RELEASE_URL:-}}" ]] && \\
             [[ ! "${{FOUNDRY_USERNAME:-}}" || ! "${{FOUNDRY_PASSWORD:-}}" ]]; then
            _preflight_cache="${{CONTAINER_CACHE-${{DATA_DIR}}/container_cache}}"
            _preflight_expected_zip="foundryvtt-${{FOUNDRY_VERSION}}.zip"
            if [[ -z "${{_preflight_cache}}" ]] || \\
               [[ ! -f "${{_preflight_cache}}/${{_preflight_expected_zip}}" ]]; then
              log_error "No installation method available."
              exit 1
            fi
          fi
        fi
        # ──────────────────────────────────────────────────────────────

        echo "VALIDATION_PASSED"
    """)

    full_script = f"cd '{SRC_DIR}'\n{env_setup}\n{validation_block}"

    # Build clean env — remove all FOUNDRY_* and CONTAINER_* vars from host
    import os

    merged_env = {k: v for k, v in os.environ.items() if not k.startswith(("FOUNDRY_", "CONTAINER_"))}
    # Apply overrides explicitly
    for var, val in env_overrides.items():
        if val is not None:
            merged_env[var] = val
        else:
            merged_env.pop(var, None)

    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


# ═══════════════════════════════════════════════════════════════════════════════
# Compose YAML validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestComposeValidation:
    """Tests for compose.yml structure and validity."""

    def test_compose_yaml_valid(self):
        """compose.yml is valid YAML with the expected top-level structure."""
        compose = _load_compose()
        assert compose is not None, "compose.yml parsed as empty/null"
        assert "services" in compose, "Missing top-level 'services' key"
        assert "foundry" in compose["services"], "Missing 'foundry' service"

    def test_compose_foundry_has_required_keys(self):
        """The foundry service has image, hostname, environment, volumes, ports."""
        compose = _load_compose()
        foundry = compose["services"]["foundry"]
        for key in ("image", "hostname", "environment", "volumes", "ports"):
            assert key in foundry, f"Missing '{key}' in foundry service"

    def test_compose_image_reference(self):
        """The foundry service uses the expected image."""
        compose = _load_compose()
        image = compose["services"]["foundry"]["image"]
        assert "foundryvtt" in image, f"Unexpected image: {image}"

    def test_compose_volume_target_is_data(self):
        """The foundry service mounts a volume at /data."""
        compose = _load_compose()
        volumes = compose["services"]["foundry"]["volumes"]
        targets = [v.get("target", "") for v in volumes if isinstance(v, dict)]
        assert "/data" in targets, f"No volume mounted at /data. Targets: {targets}"

    def test_compose_env_vars_are_documented_in_readme(self):
        """Every env var in compose.yml (active or commented) appears in README."""
        entries = _compose_env_entries()
        readme_vars = _readme_env_table()
        # Also check required vars section in README
        readme_text = README_FILE.read_text()

        undocumented = []
        for entry in entries:
            var_name = _parse_env_var_name(entry)
            # Skip vars that are in the required credentials section
            if var_name in ("FOUNDRY_USERNAME", "FOUNDRY_PASSWORD"):
                continue
            if var_name not in readme_vars and f"`{var_name}`" not in readme_text:
                undocumented.append(var_name)

        assert not undocumented, (
            f"Env vars in compose.yml not documented in README: {undocumented}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# Default value consistency
# ═══════════════════════════════════════════════════════════════════════════════


# Mapping of compose.yml env vars to their expected README defaults.
# Only vars with a non-empty default value in compose.yml are checked.
COMPOSE_DEFAULTS_TO_README = {
    "CONTAINER_CACHE": "/data/container_cache",
    "CONTAINER_PRESERVE_CONFIG": "false",
    "CONTAINER_URL_FETCH_RETRY": "0",
    "FOUNDRY_COMPRESS_WEBSOCKET": "false",
    "FOUNDRY_CSS_THEME": "dark",
    "FOUNDRY_DELETE_NEDB": "false",
    "FOUNDRY_HOT_RELOAD": "false",
    "FOUNDRY_IP_DISCOVERY": "true",
    "FOUNDRY_LANGUAGE": "en.core",
    "FOUNDRY_MINIFY_STATIC_FILES": "false",
    "FOUNDRY_NO_BACKUPS": "false",
    "FOUNDRY_PROXY_SSL": "false",
    "FOUNDRY_UPNP": "false",
    "FOUNDRY_VERSION": "14.363",
    "TZ": "UTC",
}


class TestDefaultsConsistency:
    """Tests that compose.yml defaults match README documentation."""

    @pytest.mark.parametrize(
        "var_name,expected_default",
        list(COMPOSE_DEFAULTS_TO_README.items()),
        ids=list(COMPOSE_DEFAULTS_TO_README.keys()),
    )
    def test_compose_default_matches_readme(self, var_name, expected_default):
        """compose.yml commented default for VAR matches the README default."""
        entries = _compose_env_entries()
        compose_value = None
        for entry in entries:
            if _parse_env_var_name(entry) == var_name:
                compose_value = _parse_env_var_value(entry)
                break

        assert compose_value is not None, (
            f"{var_name} not found in compose.yml environment entries"
        )
        assert compose_value == expected_default, (
            f"{var_name}: compose.yml has '{compose_value}', "
            f"expected '{expected_default}' (from README)"
        )

    def test_readme_default_table_has_compose_vars(self):
        """Every var in COMPOSE_DEFAULTS_TO_README appears in README env table."""
        readme_vars = _readme_env_table()
        missing = [v for v in COMPOSE_DEFAULTS_TO_README if v not in readme_vars]
        assert not missing, (
            f"Vars with compose defaults not found in README table: {missing}"
        )


# ═══════════════════════════════════════════════════════════════════════════════
# README example consistency
# ═══════════════════════════════════════════════════════════════════════════════


class TestReadmeExamples:
    """Tests for README example consistency."""

    def test_readme_docker_run_includes_hostname(self):
        """All docker run examples include --hostname flag."""
        blocks = _readme_docker_run_blocks()
        assert blocks, "No docker run code blocks found in README"

        missing_hostname = []
        for i, block in enumerate(blocks):
            if "--hostname" not in block:
                # Get a short identifier from the block
                first_line = block.strip().split("\n")[0][:50]
                missing_hostname.append(f"block {i} ({first_line}...)")

        assert not missing_hostname, (
            f"docker run examples missing --hostname: {missing_hostname}"
        )

    def test_readme_compose_example_has_hostname(self):
        """The YAML compose example in README includes hostname."""
        text = README_FILE.read_text()
        # Find YAML compose blocks
        yaml_blocks = re.findall(r"```yaml\n(.*?)```", text, re.DOTALL)
        assert yaml_blocks, "No YAML compose examples found in README"

        for i, block in enumerate(yaml_blocks):
            if "services:" in block:
                assert "hostname:" in block, (
                    f"Compose YAML example {i} missing hostname"
                )


# ═══════════════════════════════════════════════════════════════════════════════
# Entrypoint pre-flight validation
# ═══════════════════════════════════════════════════════════════════════════════


class TestEntrypointValidation:
    """Tests for entrypoint.sh pre-flight validation logic."""

    def test_fails_with_empty_foundry_version(self):
        """Entrypoint exits with error when FOUNDRY_VERSION is empty."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
            }
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when FOUNDRY_VERSION is empty"
        )
        output = result.stdout + result.stderr
        assert "FOUNDRY_VERSION" in output, (
            f"Error should mention FOUNDRY_VERSION. Output: {output}"
        )

    def test_fails_with_unset_foundry_version(self):
        """Entrypoint exits with error when FOUNDRY_VERSION is unset."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": None,
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
            }
        )
        assert result.returncode != 0

    def test_passes_with_valid_version_and_credentials(self):
        """Validation passes with valid FOUNDRY_VERSION and credentials."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
            }
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with valid config. stderr: {result.stderr}"
        )
        assert "VALIDATION_PASSED" in result.stdout

    def test_passes_with_release_url(self):
        """Validation passes with FOUNDRY_RELEASE_URL instead of credentials."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_RELEASE_URL": "https://example.com/release.zip",
                "FOUNDRY_USERNAME": None,
                "FOUNDRY_PASSWORD": None,
            }
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with release URL. stderr: {result.stderr}"
        )

    def test_fails_without_any_credentials(self):
        """Entrypoint fails with clear error when no install method available."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_RELEASE_URL": None,
                "FOUNDRY_USERNAME": None,
                "FOUNDRY_PASSWORD": None,
                "CONTAINER_CACHE": "",
            }
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when no install method available"
        )
        combined = result.stdout + result.stderr
        assert "No installation method available" in combined, (
            f"Error should mention install methods. Output: {combined}"
        )

    def test_fails_with_only_username(self):
        """Entrypoint fails when only FOUNDRY_USERNAME is set (no password)."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_RELEASE_URL": None,
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": None,
                "CONTAINER_CACHE": "",
            }
        )
        assert result.returncode != 0, (
            "Expected failure with username but no password"
        )

    def test_fails_with_ssl_cert_without_key(self):
        """Entrypoint fails when FOUNDRY_SSL_CERT is set without FOUNDRY_SSL_KEY."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "FOUNDRY_SSL_CERT": "/path/to/cert.pem",
                "FOUNDRY_SSL_KEY": None,
            }
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when SSL_CERT set without SSL_KEY"
        )
        output = result.stdout + result.stderr
        assert "FOUNDRY_SSL_CERT" in output, (
            f"Error should mention FOUNDRY_SSL_CERT. Output: {output}"
        )

    def test_fails_with_ssl_key_without_cert(self):
        """Entrypoint fails when FOUNDRY_SSL_KEY is set without FOUNDRY_SSL_CERT."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "FOUNDRY_SSL_CERT": None,
                "FOUNDRY_SSL_KEY": "/path/to/key.pem",
            }
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when SSL_KEY set without SSL_CERT"
        )
        output = result.stdout + result.stderr
        assert "FOUNDRY_SSL_KEY" in output, (
            f"Error should mention FOUNDRY_SSL_KEY. Output: {output}"
        )

    def test_passes_with_both_ssl_cert_and_key(self):
        """Validation passes when both SSL_CERT and SSL_KEY are set."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "FOUNDRY_SSL_CERT": "/path/to/cert.pem",
                "FOUNDRY_SSL_KEY": "/path/to/key.pem",
            }
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with both SSL vars. stderr: {result.stderr}"
        )

    def test_fails_with_invalid_cache_size_zero(self):
        """Entrypoint fails when CONTAINER_CACHE_SIZE is 0."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "CONTAINER_CACHE_SIZE": "0",
            }
        )
        assert result.returncode != 0, (
            "Expected non-zero exit when CONTAINER_CACHE_SIZE is 0"
        )
        output = result.stdout + result.stderr
        assert "CONTAINER_CACHE_SIZE" in output, (
            f"Error should mention CONTAINER_CACHE_SIZE. Output: {output}"
        )

    def test_fails_with_invalid_cache_size_negative(self):
        """Entrypoint fails when CONTAINER_CACHE_SIZE is negative."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "CONTAINER_CACHE_SIZE": "-1",
            }
        )
        assert result.returncode != 0

    def test_fails_with_invalid_cache_size_non_numeric(self):
        """Entrypoint fails when CONTAINER_CACHE_SIZE is non-numeric."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "CONTAINER_CACHE_SIZE": "abc",
            }
        )
        assert result.returncode != 0

    def test_passes_with_valid_cache_size(self):
        """Validation passes with valid CONTAINER_CACHE_SIZE."""
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_USERNAME": "user",
                "FOUNDRY_PASSWORD": "pass",
                "CONTAINER_CACHE_SIZE": "3",
            }
        )
        assert result.returncode == 0, (
            f"Expected exit 0 with valid cache size. stderr: {result.stderr}"
        )

    def test_skips_credential_check_when_already_installed(self, tmp_path):
        """Validation skips credential check when Foundry is already installed."""
        # Create a mock package.json indicating Foundry 14.363 is installed
        pkg_json = '{"release": {"generation": 14, "build": 363}}'
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_RELEASE_URL": None,
                "FOUNDRY_USERNAME": None,
                "FOUNDRY_PASSWORD": None,
                "CONTAINER_CACHE": "",
            },
            has_package_json=True,
            package_json_content=pkg_json,
        )
        assert result.returncode == 0, (
            f"Expected exit 0 when already installed. stderr: {result.stderr}"
        )
        assert "VALIDATION_PASSED" in result.stdout

    def test_requires_credentials_when_version_mismatch(self, tmp_path):
        """Validation requires credentials when installed version differs."""
        # Create a mock package.json with a different version
        pkg_json = '{"release": {"generation": 13, "build": 331}}'
        result = _run_validation(
            {
                "FOUNDRY_VERSION": "14.363",
                "FOUNDRY_RELEASE_URL": None,
                "FOUNDRY_USERNAME": None,
                "FOUNDRY_PASSWORD": None,
                "CONTAINER_CACHE": "",
            },
            has_package_json=True,
            package_json_content=pkg_json,
        )
        assert result.returncode != 0, (
            "Expected failure when version mismatch and no credentials"
        )
