"""Unit tests for src/validate_permissions.sh.

Tests are driven via subprocess calls to bash, sourcing validate_permissions.sh
directly. logging.sh is stubbed out so tests have no terminal-color side-effects.
"""

# Standard Python Libraries
import os
from pathlib import Path
import stat
import subprocess
import textwrap

# Third-Party Libraries
import pytest

# Absolute path to the src/ directory so bash can find the scripts.
SRC_DIR = Path(__file__).parent.parent / "src"


def _run(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources validate_permissions.sh with logging stubbed.

    Logging functions emit markers (LOG_INFO, LOG_WARN, LOG_ERROR, LOG_DEBUG)
    that tests can grep for in stdout/stderr.
    """
    log_stubs = textwrap.dedent("""\
        log()       { echo "LOG_INFO $*"; }
        log_debug() { echo "LOG_DEBUG $*"; }
        log_warn()  { echo "LOG_WARN $*"; }
        log_error() { echo "LOG_ERROR $*"; }
    """)
    full_script = f"cd '{SRC_DIR}'\n{log_stubs}\nsource validate_permissions.sh\n{script}"
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


# ── Default UID/GID (writable directory) ──────────────────────────────────────


def test_default_uid_passes_all_checks(tmp_path: Path) -> None:
    """All checks pass when the data directory is writable and files are executable."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script)
    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}. stderr: {result.stderr}"
    # Config subdirectory should have been created
    assert (tmp_path / "Config").exists(), "Config directory should be created"


def test_identity_logged_in_debug_mode(tmp_path: Path) -> None:
    """Identity (uid/gid) is logged in debug mode."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"CONTAINER_VERBOSE": "true"})
    assert result.returncode == 0, result.stderr
    assert "LOG_DEBUG Running as:" in result.stdout, "Identity should be logged"


# ── Custom UID/GID (system range warnings) ────────────────────────────────────


def test_root_uid_warns(tmp_path: Path) -> None:
    """Running as root (UID 0) produces a warning but is not fatal."""
    # We can't actually run as root in a test, so we mock id -u to return 0
    script = textwrap.dedent(f"""\
        id() {{
          case "$1" in
            -u) echo 0 ;;
            -g) echo 0 ;;
            -un) echo root ;;
            *) command id "$@" ;;
          esac
        }}
        export -f id
        validate_permissions {tmp_path}
    """)
    result = _run(script)
    # Should not fail (warn only)
    assert result.returncode == 0, f"Root UID should warn, not fail. stderr: {result.stderr}"
    assert "LOG_WARN" in result.stdout and "root" in result.stdout.lower(), (
        "Should warn about running as root"
    )


def test_system_uid_warns(tmp_path: Path) -> None:
    """Running as a system UID (< 1000, not 'node') produces a warning."""
    script = textwrap.dedent(f"""\
        id() {{
          case "$1" in
            -u) echo 500 ;;
            -g) echo 500 ;;
            -un) echo daemon ;;
            *) command id "$@" ;;
          esac
        }}
        export -f id
        validate_permissions {tmp_path}
    """)
    result = _run(script)
    assert result.returncode == 0, f"System UID should warn, not fail. stderr: {result.stderr}"
    assert "LOG_WARN" in result.stdout and "500" in result.stdout, (
        "Should warn about system-range UID"
    )


def test_node_user_uid_no_warn(tmp_path: Path) -> None:
    """The 'node' user (UID 1000) should not trigger a system-range warning."""
    script = textwrap.dedent(f"""\
        id() {{
          case "$1" in
            -u) echo 1000 ;;
            -g) echo 1000 ;;
            -un) echo node ;;
            *) command id "$@" ;;
          esac
        }}
        export -f id
        validate_permissions {tmp_path}
    """)
    result = _run(script)
    assert result.returncode == 0, result.stderr
    # Should not warn about system range
    assert "system range" not in result.stdout.lower(), (
        "node user should not trigger system-range warning"
    )


# ── Directory owner mismatch (read-only data dir) ─────────────────────────────


def test_readonly_data_dir_fails(tmp_path: Path) -> None:
    """A read-only data directory causes a fatal failure."""
    tmp_path.chmod(0o555)  # read + execute only
    try:
        script = textwrap.dedent(f"""\
            validate_permissions {tmp_path}
        """)
        result = _run(script)
        assert result.returncode != 0, "Read-only data dir should cause fatal exit"
        assert "LOG_ERROR" in result.stdout and "write test failed" in result.stdout.lower(), (
            "Should report write test failure"
        )
    finally:
        # Restore permissions for cleanup
        tmp_path.chmod(0o755)


def test_error_message_includes_uid_gid(tmp_path: Path) -> None:
    """Fatal permission failure includes the current uid:gid in the error."""
    tmp_path.chmod(0o555)
    try:
        script = textwrap.dedent(f"""\
            validate_permissions {tmp_path}
        """)
        result = _run(script)
        assert result.returncode != 0
        assert "uid:gid" in result.stdout.lower(), "Error should include uid:gid"
    finally:
        tmp_path.chmod(0o755)


def test_error_message_includes_discussion_link(tmp_path: Path) -> None:
    """Fatal permission failure includes a link to discussion #1197."""
    tmp_path.chmod(0o555)
    try:
        script = textwrap.dedent(f"""\
            validate_permissions {tmp_path}
        """)
        result = _run(script)
        assert result.returncode != 0
        assert "1197" in result.stdout, "Error should include discussion #1197 link"
    finally:
        tmp_path.chmod(0o755)


# ── Non-executable file failure ───────────────────────────────────────────────


def test_non_executable_launcher_fails(tmp_path: Path) -> None:
    """A non-executable launcher.sh causes a fatal failure."""
    # Make launcher.sh non-executable temporarily
    launcher = SRC_DIR / "launcher.sh"
    original_mode = launcher.stat().st_mode
    launcher.chmod(original_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    try:
        script = textwrap.dedent(f"""\
            validate_permissions {tmp_path}
        """)
        result = _run(script)
        assert result.returncode != 0, "Non-executable launcher.sh should cause fatal exit"
        assert "LOG_ERROR" in result.stdout and "launcher.sh" in result.stdout, (
            "Error should name the non-executable file"
        )
    finally:
        # Restore original permissions
        launcher.chmod(original_mode)


def test_error_names_missing_file(tmp_path: Path) -> None:
    """Error message names the specific file that is not executable."""
    launcher = SRC_DIR / "launcher.sh"
    original_mode = launcher.stat().st_mode
    launcher.chmod(original_mode & ~stat.S_IXUSR & ~stat.S_IXGRP & ~stat.S_IXOTH)
    try:
        script = textwrap.dedent(f"""\
            validate_permissions {tmp_path}
        """)
        result = _run(script)
        assert result.returncode != 0
        # Should explicitly mention launcher.sh
        assert "launcher.sh" in result.stdout, (
            "Error should explicitly name launcher.sh as non-executable"
        )
    finally:
        launcher.chmod(original_mode)


# ── CONTAINER_UMASK format ────────────────────────────────────────────────────


def test_valid_umask_accepted(tmp_path: Path) -> None:
    """A valid octal umask (e.g., 0022) produces no warning."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"CONTAINER_UMASK": "0022"})
    assert result.returncode == 0, result.stderr
    # Should not warn about invalid umask
    assert "not a valid octal umask" not in result.stdout, (
        "Valid umask should not produce a warning"
    )


def test_valid_umask_three_digits(tmp_path: Path) -> None:
    """A 3-digit octal umask (e.g., 022) is also accepted."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"CONTAINER_UMASK": "022"})
    assert result.returncode == 0, result.stderr
    assert "not a valid octal umask" not in result.stdout


def test_invalid_umask_warns(tmp_path: Path) -> None:
    """An invalid umask (e.g., 9999) produces a warning but is not fatal."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"CONTAINER_UMASK": "9999"})
    assert result.returncode == 0, f"Invalid umask should warn, not fail. stderr: {result.stderr}"
    assert "LOG_WARN" in result.stdout and "not a valid octal umask" in result.stdout, (
        "Should warn about invalid umask format"
    )


def test_invalid_umask_non_numeric(tmp_path: Path) -> None:
    """A non-numeric umask produces a warning."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"CONTAINER_UMASK": "abcd"})
    assert result.returncode == 0, result.stderr
    assert "not a valid octal umask" in result.stdout


def test_no_umask_no_warning(tmp_path: Path) -> None:
    """When CONTAINER_UMASK is not set, no umask warning is produced."""
    merged_env = {k: v for k, v in os.environ.items() if k != "CONTAINER_UMASK"}
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env=merged_env)
    assert result.returncode == 0, result.stderr
    assert "umask" not in result.stdout.lower() or "LOG_DEBUG" in result.stdout, (
        "No umask warning when CONTAINER_UMASK is unset"
    )


# ── Deprecated environment variables ──────────────────────────────────────────


def test_deprecated_env_warns(tmp_path: Path) -> None:
    """Setting a deprecated env var (FOUNDRY_UID) produces a warning."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"FOUNDRY_UID": "1001"})
    assert result.returncode == 0, result.stderr
    assert "LOG_WARN" in result.stdout and "FOUNDRY_UID" in result.stdout, (
        "Should warn about deprecated FOUNDRY_UID"
    )


def test_multiple_deprecated_envs_warn(tmp_path: Path) -> None:
    """Setting multiple deprecated env vars produces warnings for each."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env={"FOUNDRY_UID": "1001", "FOUNDRY_GID": "1001"})
    assert result.returncode == 0, result.stderr
    assert "FOUNDRY_UID" in result.stdout, "Should warn about FOUNDRY_UID"
    assert "FOUNDRY_GID" in result.stdout, "Should warn about FOUNDRY_GID"


def test_no_deprecated_envs_no_warning(tmp_path: Path) -> None:
    """When no deprecated env vars are set, no deprecation warnings are produced."""
    # Unset all deprecated vars
    merged_env = {
        k: v
        for k, v in os.environ.items()
        if k not in ("FOUNDRY_UID", "FOUNDRY_GID", "CONTAINER_PRESERVE_OWNER", "TIMEZONE")
    }
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script, env=merged_env)
    assert result.returncode == 0, result.stderr
    assert "deprecated" not in result.stdout.lower() or "LOG_DEBUG" in result.stdout, (
        "No deprecation warnings when deprecated vars are unset"
    )


# ── Config directory ──────────────────────────────────────────────────────────


def test_config_dir_created(tmp_path: Path) -> None:
    """The Config subdirectory is created when the data directory is writable."""
    script = textwrap.dedent(f"""\
        validate_permissions {tmp_path}
    """)
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert (tmp_path / "Config").exists(), "Config directory should be created"


def test_config_dir_creation_failure_fatal(tmp_path: Path) -> None:
    """Config directory creation failure is fatal when data dir is read-only."""
    # Make data dir read-only so Config cannot be created
    tmp_path.chmod(0o555)
    try:
        script = textwrap.dedent(f"""\
            validate_permissions {tmp_path}
        """)
        result = _run(script)
        # Should fail at data dir permissions check (before config dir)
        assert result.returncode != 0, "Should fail when data dir is read-only"
    finally:
        tmp_path.chmod(0o755)
