"""Unit tests for src/validate.sh.

Tests are driven via subprocess calls to bash, sourcing validate.sh directly.
logging.sh is stubbed out so tests have no terminal-color side-effects.

Covers:
  - Normal startup dry-run / command expansion
  - Missing path failures
  - Non-writable directory failures
"""

# Standard Python Libraries
import os
from pathlib import Path
import shutil
import subprocess
import textwrap

# Third-Party Libraries
import pytest

# Absolute path to the src/ directory so bash can find validate.sh / logging.sh.
SRC_DIR = Path(__file__).parent.parent / "src"

LOG_STUBS = textwrap.dedent("""\
    log()       { :; }
    log_debug() { :; }
    log_warn()  { :; }
    log_error() { echo "[error] $*" >&2; }
""")


def _run(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources validate.sh with logging stubbed out."""
    full_script = f"cd '{SRC_DIR}'\n{LOG_STUBS}\nsource validate.sh\n{script}"
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


# ── require_file ─────────────────────────────────────────────────────────────


def test_require_file_existing(tmp_path: Path) -> None:
    """require_file succeeds when the file exists."""
    target = tmp_path / "some_file.txt"
    target.write_text("content")
    result = _run(f'require_file "{target}"')
    assert result.returncode == 0


def test_require_file_missing(tmp_path: Path) -> None:
    """require_file exits 1 with a 'File not found' message when file is absent."""
    target = tmp_path / "nonexistent.txt"
    result = _run(f'require_file "{target}" "test config"')
    assert result.returncode == 1
    assert "File not found" in result.stderr
    assert "test config" in result.stderr


# ── require_dir ──────────────────────────────────────────────────────────────


def test_require_dir_existing(tmp_path: Path) -> None:
    """require_dir succeeds when the directory exists."""
    result = _run(f'require_dir "{tmp_path}"')
    assert result.returncode == 0


def test_require_dir_missing(tmp_path: Path) -> None:
    """require_dir exits 1 with a 'Directory not found' message."""
    target = tmp_path / "nonexistent_dir"
    result = _run(f'require_dir "{target}" "data directory"')
    assert result.returncode == 1
    assert "Directory not found" in result.stderr
    assert "data directory" in result.stderr


# ── require_executable ───────────────────────────────────────────────────────


def test_require_executable_ok(tmp_path: Path) -> None:
    """require_executable succeeds on an executable file."""
    target = tmp_path / "run.sh"
    target.write_text("#!/bin/bash\n")
    target.chmod(0o755)
    result = _run(f'require_executable "{target}"')
    assert result.returncode == 0


def test_require_executable_not_executable(tmp_path: Path) -> None:
    """require_executable exits 1 when the file is not executable."""
    target = tmp_path / "run.sh"
    target.write_text("#!/bin/bash\n")
    target.chmod(0o644)
    result = _run(f'require_executable "{target}" "launcher script"')
    assert result.returncode == 1
    assert "not executable" in result.stderr
    assert "launcher script" in result.stderr


def test_require_executable_missing(tmp_path: Path) -> None:
    """require_executable exits 1 when the file does not exist."""
    target = tmp_path / "missing.sh"
    result = _run(f'require_executable "{target}"')
    assert result.returncode == 1
    assert "File not found" in result.stderr


# ── require_writable_dir ─────────────────────────────────────────────────────


def test_require_writable_dir_ok(tmp_path: Path) -> None:
    """require_writable_dir succeeds on a writable directory and cleans up."""
    result = _run(f'require_writable_dir "{tmp_path}" "data volume"')
    assert result.returncode == 0
    # The test file should have been cleaned up
    test_file = tmp_path / ".container-permissions-test.txt"
    assert not test_file.exists(), "Permissions test file should be cleaned up"


def test_require_writable_dir_readonly(tmp_path: Path) -> None:
    """require_writable_dir exits 1 on a read-only directory."""
    if os.getuid() == 0:
        pytest.skip("Cannot test read-only directory as root")
    readonly_dir = tmp_path / "readonly"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o555)
    try:
        result = _run(f'require_writable_dir "{readonly_dir}" "data volume"')
        assert result.returncode == 1
        assert "write test failed" in result.stderr
        assert "insufficient permissions" in result.stderr
        assert "discussions/1197" in result.stderr
    finally:
        # Restore permissions so pytest can clean up
        readonly_dir.chmod(0o755)


def test_require_writable_dir_missing(tmp_path: Path) -> None:
    """require_writable_dir exits 1 when the directory does not exist."""
    target = tmp_path / "nonexistent"
    result = _run(f'require_writable_dir "{target}" "data volume"')
    assert result.returncode == 1
    assert "Directory not found" in result.stderr


# ── require_env ──────────────────────────────────────────────────────────────


def test_require_env_set() -> None:
    """require_env succeeds when the variable is set and non-empty."""
    result = _run('MY_VAR="hello"; require_env MY_VAR')
    assert result.returncode == 0


def test_require_env_unset() -> None:
    """require_env exits 1 when the variable is not set."""
    result = _run('unset MY_VAR; require_env MY_VAR "my setting"')
    assert result.returncode == 1
    assert "MY_VAR" in result.stderr
    assert "not set" in result.stderr
    assert "my setting" in result.stderr


def test_require_env_empty() -> None:
    """require_env exits 1 when the variable is set to an empty string."""
    result = _run('MY_VAR=""; require_env MY_VAR')
    assert result.returncode == 1
    assert "not set" in result.stderr


# ── Consistent error format ──────────────────────────────────────────────────


def test_error_format_includes_uid_gid(tmp_path: Path) -> None:
    """_validate_fail output includes the uid:gid context line."""
    target = tmp_path / "missing.txt"
    result = _run(f'require_file "{target}"')
    assert result.returncode == 1
    assert "uid:gid:" in result.stderr


def test_writable_dir_error_includes_discussion_link(tmp_path: Path) -> None:
    """require_writable_dir failure includes the troubleshooting discussion link."""
    if os.getuid() == 0:
        pytest.skip("Cannot test read-only directory as root")
    readonly_dir = tmp_path / "ro"
    readonly_dir.mkdir()
    readonly_dir.chmod(0o555)
    try:
        result = _run(f'require_writable_dir "{readonly_dir}" "test"')
        assert "felddy/foundryvtt-docker/discussions/1197" in result.stderr
    finally:
        readonly_dir.chmod(0o755)


# ── Dry-run: entrypoint.sh --version ─────────────────────────────────────────


def test_entrypoint_version_dryrun(tmp_path: Path) -> None:
    """entrypoint.sh --version exits 0 and prints the image version.

    This verifies the entrypoint still works after sourcing validate.sh.
    """
    workdir = tmp_path / "workdir"
    workdir.mkdir()

    # Copy all needed shell scripts into a flat working directory
    for script in ["entrypoint.sh", "logging.sh", "backoff.sh", "validate.sh"]:
        shutil.copy2(SRC_DIR / script, workdir / script)

    # Create image_version.txt (required by entrypoint.sh)
    (workdir / "image_version.txt").write_text("14.363.0")

    env = {**os.environ, "FOUNDRY_VERSION": "14.363"}
    result = subprocess.run(
        ["bash", str(workdir / "entrypoint.sh"), "--version"],
        capture_output=True,
        text=True,
        cwd=str(workdir),
        env=env,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    assert "14.363.0" in result.stdout.strip()


# ── Dry-run: launcher command expansion ──────────────────────────────────────


def test_launcher_command_expansion() -> None:
    """Launcher argument-building pattern correctly expands optional flags.

    Tests the same set/shift pattern used by launcher.sh to build the final
    exec argument list, ensuring validate.sh sourcing doesn't interfere.
    """
    script = textwrap.dedent(f"""\
        cd '{SRC_DIR}'
        {LOG_STUBS}
        source validate.sh

        # Simulate launcher.sh argument building with CMD defaults
        set -- "resources/app/main.mjs" "--port=30000" "--headless" "--noupdate" "--dataPath=/data"

        FOUNDRY_IP_DISCOVERY=false
        if [[ "${{FOUNDRY_IP_DISCOVERY:-}}" == "false" ]]; then
          set -- "$@" --noipdiscovery
        fi

        FOUNDRY_LOG_SIZE=50
        if [[ "${{FOUNDRY_LOG_SIZE:-}}" ]]; then
          set -- "$@" --logsize="${{FOUNDRY_LOG_SIZE}}"
        fi

        FOUNDRY_MAX_LOGS=5
        if [[ "${{FOUNDRY_MAX_LOGS:-}}" ]]; then
          set -- "$@" --maxlogs="${{FOUNDRY_MAX_LOGS}}"
        fi

        # Output final argument list
        echo "$@"
    """)
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0, f"stderr: {result.stderr}"
    output = result.stdout.strip()
    assert "resources/app/main.mjs" in output
    assert "--port=30000" in output
    assert "--noipdiscovery" in output
    assert "--logsize=50" in output
    assert "--maxlogs=5" in output


# ── Integration: service key validation through require_env ──────────────────


def test_service_key_without_config_fails() -> None:
    """FOUNDRY_SERVICE_KEY set without FOUNDRY_SERVICE_CONFIG fails via require_env.

    This mirrors the launcher.sh validation path after the refactor.
    """
    script = textwrap.dedent(f"""\
        cd '{SRC_DIR}'
        {LOG_STUBS}
        source validate.sh

        FOUNDRY_SERVICE_KEY="test-key"
        unset FOUNDRY_SERVICE_CONFIG 2>/dev/null || true

        if [[ "${{FOUNDRY_SERVICE_KEY:-}}" ]]; then
          require_env "FOUNDRY_SERVICE_CONFIG" "service provider configuration"
        fi
        echo "should not reach here"
    """)
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 1
    assert "FOUNDRY_SERVICE_CONFIG" in result.stderr
    assert "should not reach here" not in result.stdout


def test_service_key_with_config_succeeds() -> None:
    """FOUNDRY_SERVICE_KEY with FOUNDRY_SERVICE_CONFIG passes validation."""
    script = textwrap.dedent(f"""\
        cd '{SRC_DIR}'
        {LOG_STUBS}
        source validate.sh

        FOUNDRY_SERVICE_KEY="test-key"
        FOUNDRY_SERVICE_CONFIG="/path/to/config"

        if [[ "${{FOUNDRY_SERVICE_KEY:-}}" ]]; then
          require_env "FOUNDRY_SERVICE_CONFIG" "service provider configuration"
        fi
        echo "ok"
    """)
    result = subprocess.run(
        ["bash", "-c", script],
        capture_output=True,
        text=True,
        timeout=10,
    )
    assert result.returncode == 0
    assert "ok" in result.stdout
