"""Unit tests for src/resolve_release.sh.

Tests are driven via subprocess calls to bash, sourcing resolve_release.sh
directly.  logging.sh is stubbed out so tests have no terminal-color side-effects.
"""

# Standard Python Libraries
import json
import os
from pathlib import Path
import subprocess
import textwrap

# Third-Party Libraries
import pytest

# Absolute path to the src/ directory so bash can find resolve_release.sh.
SRC_DIR = Path(__file__).parent.parent / "src"


def _run(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources resolve_release.sh with logging stubbed out."""
    log_stubs = textwrap.dedent("""\
        log()       { :; }
        log_debug() { :; }
        log_warn()  { :; }
        log_error() { :; }
    """)
    full_script = f"cd '{SRC_DIR}'\n{log_stubs}\nsource resolve_release.sh\n{script}"
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


# ── validate_version_format ──────────────────────────────────────────────────


VALID_VERSIONS = [
    "14.363",
    "1.0",
    "99.999",
    "0.1",
    "12.345",
    "100.1000",
]

INVALID_VERSIONS = [
    "",        # empty
    "14",      # no dot
    "abc",     # letters
    "14.",     # trailing dot
    ".363",    # leading dot
    "14.363.0", # three components (semver, not generation.build)
    "14.abc",  # non-numeric build
    "v14.363", # v prefix
    "14.363 ", # trailing space
    "14 .363", # space in middle
]


@pytest.mark.parametrize("version", VALID_VERSIONS)
def test_valid_version_formats(version: str):
    """Valid 'generation.build' versions should pass validation."""
    result = _run(f'validate_version_format "{version}"')
    assert result.returncode == 0, f"Version '{version}' should be valid"


@pytest.mark.parametrize("version", INVALID_VERSIONS)
def test_invalid_version_formats(version: str):
    """Invalid version formats should fail validation."""
    result = _run(f'validate_version_format "{version}"')
    assert result.returncode != 0, f"Version '{version}' should be invalid"


# ── check_installed_version ──────────────────────────────────────────────────


def test_installed_version_match(tmp_path: Path):
    """When installed version matches requested, should return 'false' (no install needed)."""
    resources_dir = tmp_path / "resources" / "app"
    resources_dir.mkdir(parents=True)
    package_json = {
        "release": {
            "generation": 14,
            "build": 363,
        }
    }
    (resources_dir / "package.json").write_text(json.dumps(package_json))

    result = _run(f'check_installed_version "14.363" "{tmp_path}"')
    assert result.returncode == 0
    assert result.stdout.strip() == "false"


def test_installed_version_mismatch(tmp_path: Path):
    """When installed version differs, should return 'true' and remove resources."""
    resources_dir = tmp_path / "resources" / "app"
    resources_dir.mkdir(parents=True)
    package_json = {
        "release": {
            "generation": 13,
            "build": 300,
        }
    }
    (resources_dir / "package.json").write_text(json.dumps(package_json))

    result = _run(f'check_installed_version "14.363" "{tmp_path}"')
    assert result.returncode == 0
    assert result.stdout.strip() == "true"
    # Resources directory should be removed on mismatch
    assert not (tmp_path / "resources").exists()


def test_installed_version_no_package_json(tmp_path: Path):
    """When no package.json exists, should return 'true' (install required)."""
    result = _run(f'check_installed_version "14.363" "{tmp_path}"')
    assert result.returncode == 0
    assert result.stdout.strip() == "true"


# ── resolve_presigned_url ────────────────────────────────────────────────────


def test_release_url_env_takes_precedence(tmp_path: Path):
    """FOUNDRY_RELEASE_URL should be used directly, skipping authentication."""
    cookiejar = str(tmp_path / "cookiejar.json")
    test_url = "https://example.com/foundry.zip?sig=abc123"

    result = _run(
        f'resolve_presigned_url "{cookiejar}" "test-agent" "14.363"',
        env={
            "FOUNDRY_RELEASE_URL": test_url,
            "FOUNDRY_USERNAME": "",
            "FOUNDRY_PASSWORD": "",
        },
    )
    assert result.returncode == 0
    assert result.stdout.strip() == test_url
    # Cookie jar should NOT be created when using direct URL
    assert not Path(cookiejar).exists()


def test_release_url_empty_env_falls_through(tmp_path: Path):
    """Empty FOUNDRY_RELEASE_URL should fall through to credentials check."""
    cookiejar = str(tmp_path / "cookiejar.json")

    result = _run(
        f'resolve_presigned_url "{cookiejar}" "test-agent" "14.363"',
        env={
            "FOUNDRY_RELEASE_URL": "",
            "FOUNDRY_USERNAME": "",
            "FOUNDRY_PASSWORD": "",
        },
    )
    # No credentials and no URL → should fail
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_release_url_no_credentials_no_url(tmp_path: Path):
    """With no credentials and no URL, should return failure."""
    cookiejar = str(tmp_path / "cookiejar.json")

    result = _run(
        f'resolve_presigned_url "{cookiejar}" "test-agent" "14.363"',
        env={
            "FOUNDRY_USERNAME": "",
            "FOUNDRY_PASSWORD": "",
        },
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_release_url_auth_failure_returns_empty(tmp_path: Path):
    """When authentication fails, should return failure (empty URL)."""
    cookiejar = str(tmp_path / "cookiejar.json")

    # Mock authenticate.js to fail (placed in tmp_path, which we cd into)
    mock_auth = tmp_path / "authenticate.js"
    mock_auth.write_text("#!/bin/bash\nexit 1\n")
    mock_auth.chmod(0o755)

    result = _run(
        f'cd "{tmp_path}"\n'
        f'resolve_presigned_url "{cookiejar}" "test-agent" "14.363"',
        env={
            "FOUNDRY_USERNAME": "user",
            "FOUNDRY_PASSWORD": "pass",
        },
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_release_url_empty_after_fetch(tmp_path: Path):
    """When get_release_url.js returns empty, should return failure."""
    cookiejar = str(tmp_path / "cookiejar.json")

    # Mock authenticate.js to succeed (create cookie jar)
    mock_auth = tmp_path / "authenticate.js"
    mock_auth.write_text(f"#!/bin/bash\ntouch '{cookiejar}'\nexit 0\n")
    mock_auth.chmod(0o755)

    # Mock get_release_url.js to return empty
    mock_get_url = tmp_path / "get_release_url.js"
    mock_get_url.write_text("#!/bin/bash\nexit 0\n")
    mock_get_url.chmod(0o755)

    result = _run(
        f'cd "{tmp_path}"\n'
        f'resolve_presigned_url "{cookiejar}" "test-agent" "14.363"',
        env={
            "FOUNDRY_USERNAME": "user",
            "FOUNDRY_PASSWORD": "pass",
        },
    )
    assert result.returncode != 0
    assert result.stdout.strip() == ""


def test_release_url_successful_fetch(tmp_path: Path):
    """When get_release_url.js returns a URL, should succeed."""
    cookiejar = str(tmp_path / "cookiejar.json")
    test_url = "https://example.com/foundry.zip?sig=xyz789"

    # Mock authenticate.js to succeed
    mock_auth = tmp_path / "authenticate.js"
    mock_auth.write_text(f"#!/bin/bash\ntouch '{cookiejar}'\nexit 0\n")
    mock_auth.chmod(0o755)

    # Mock get_release_url.js to return URL
    mock_get_url = tmp_path / "get_release_url.js"
    mock_get_url.write_text(f"#!/bin/bash\necho -n '{test_url}'\nexit 0\n")
    mock_get_url.chmod(0o755)

    result = _run(
        f'cd "{tmp_path}"\n'
        f'resolve_presigned_url "{cookiejar}" "test-agent" "14.363"',
        env={
            "FOUNDRY_USERNAME": "user",
            "FOUNDRY_PASSWORD": "pass",
        },
    )
    assert result.returncode == 0
    assert result.stdout.strip() == test_url


# ── Error codes ──────────────────────────────────────────────────────────────


def test_error_codes_defined():
    """Error code constants should be defined and non-zero."""
    result = _run(
        'echo "INVALID=${RESOLVE_ERR_INVALID_VERSION} NO_URL=${RESOLVE_ERR_NO_URL}"'
    )
    assert result.returncode == 0
    assert "INVALID=2" in result.stdout
    assert "NO_URL=3" in result.stdout
