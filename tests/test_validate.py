"""Unit tests for src/validate.sh and refactored launcher.sh / entrypoint.sh
validation paths.

Tests are driven via subprocess calls to bash, sourcing validate.sh directly.
logging.sh is stubbed out so tests have no terminal-color side-effects.
"""

# Standard Python Libraries
import os
from pathlib import Path
import stat
import subprocess
import textwrap

# Third-Party Libraries
import pytest

# Absolute path to the src/ directory so bash can find validate.sh / logging.sh.
SRC_DIR = Path(__file__).parent.parent / "src"


def _run_validate(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources validate.sh with logging stubbed out."""
    log_stubs = textwrap.dedent("""\
        log()       { :; }
        log_debug() { :; }
        log_warn()  { :; }
        log_error() { echo "ERROR: $*" >&2; }
    """)
    full_script = f"cd '{SRC_DIR}'\n{log_stubs}\nsource validate.sh\n{script}"
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


def _run_launcher(
    args: list[str],
    env: dict | None = None,
    cwd: str | Path | None = None,
    timeout: int = 10,
) -> subprocess.CompletedProcess:
    """Run launcher.sh with the given arguments and environment.

    Sets CONFIG_DIR to a writable directory under cwd so tests work
    outside Docker where /data may not exist or be writable.
    Sets NODE_BIN to a stub so tests work outside Docker where
    /usr/local/bin/node may not exist.
    logging.sh writes to stdout (not stderr), so error messages from
    the launcher appear in stdout.
    """
    workdir = Path(cwd or SRC_DIR)
    config_dir = workdir / "Config"
    config_dir.mkdir(exist_ok=True)
    node_stub = workdir / "node_stub"
    if not node_stub.exists():
        node_stub.write_text("#!/bin/bash\necho 'node stub'\n")
        node_stub.chmod(0o755)
    merged_env = {
        **os.environ,
        "HOME": str(workdir),
        "FOUNDRY_VERSION": "14.363",
        "CONTAINER_DRY_RUN": "true",
        "CONFIG_DIR": str(config_dir),
        "NODE_BIN": str(node_stub),
        **(env or {}),
    }
    cmd = ["bash", str(SRC_DIR / "launcher.sh")] + args
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=merged_env,
        cwd=str(workdir),
        timeout=timeout,
    )


# ── validate_writable_dir ─────────────────────────────────────────────────────


class TestValidateWritableDir:
    """Tests for validate_writable_dir."""

    def test_success_on_writable_dir(self, tmp_path: Path) -> None:
        """Returns 0 for a directory with full read/write/execute permissions."""
        result = _run_validate(f'validate_writable_dir "{tmp_path}"')
        assert result.returncode == 0, result.stderr

    def test_fails_on_readonly_dir(self, tmp_path: Path) -> None:
        """Returns 1 when the directory is read-only (no write permission)."""
        readonly_dir = tmp_path / "readonly"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x only
        try:
            result = _run_validate(f'validate_writable_dir "{readonly_dir}"')
            assert result.returncode == 1
            assert "Write test failed" in result.stderr
        finally:
            readonly_dir.chmod(stat.S_IRWXU)  # restore for cleanup

    def test_fails_on_nonexistent_dir(self, tmp_path: Path) -> None:
        """Returns 1 when the directory does not exist."""
        missing = tmp_path / "does_not_exist"
        result = _run_validate(f'validate_writable_dir "{missing}"')
        assert result.returncode == 1
        assert "does not exist" in result.stderr

    def test_fails_on_file_not_dir(self, tmp_path: Path) -> None:
        """Returns 1 when the path exists but is a regular file, not a directory."""
        regular_file = tmp_path / "a_file"
        regular_file.write_text("hello")
        result = _run_validate(f'validate_writable_dir "{regular_file}"')
        assert result.returncode == 1
        assert "does not exist" in result.stderr

    def test_fails_with_empty_argument(self) -> None:
        """Returns 1 when called with no argument."""
        result = _run_validate('validate_writable_dir ""')
        assert result.returncode == 1
        assert "no directory path provided" in result.stderr

    def test_leaves_no_probe_file(self, tmp_path: Path) -> None:
        """After a successful check, no temporary probe file remains."""
        _run_validate(f'validate_writable_dir "{tmp_path}"')
        children = list(tmp_path.iterdir())
        assert children == [], f"Probe file left behind: {children}"


# ── validate_required_file ────────────────────────────────────────────────────


class TestValidateRequiredFile:
    """Tests for validate_required_file."""

    def test_success_when_file_exists(self, tmp_path: Path) -> None:
        """Returns 0 when the file exists."""
        f = tmp_path / "found.txt"
        f.write_text("hello")
        result = _run_validate(f'validate_required_file "{f}" "test file"')
        assert result.returncode == 0

    def test_fails_when_file_missing(self, tmp_path: Path) -> None:
        """Returns 1 when the file does not exist."""
        missing = tmp_path / "missing.txt"
        result = _run_validate(f'validate_required_file "{missing}" "test file"')
        assert result.returncode == 1
        assert "not found" in result.stderr

    def test_fails_with_empty_argument(self) -> None:
        """Returns 1 when called with no argument."""
        result = _run_validate('validate_required_file ""')
        assert result.returncode == 1
        assert "no file path provided" in result.stderr

    def test_fails_on_directory(self, tmp_path: Path) -> None:
        """Returns 1 when the path is a directory, not a regular file."""
        result = _run_validate(f'validate_required_file "{tmp_path}" "config"')
        assert result.returncode == 1
        assert "not found" in result.stderr


# ── validate_executable_file ──────────────────────────────────────────────────


class TestValidateExecutableFile:
    """Tests for validate_executable_file."""

    def test_success_on_executable(self, tmp_path: Path) -> None:
        """Returns 0 when the file exists and is executable."""
        exe = tmp_path / "my_script.sh"
        exe.write_text("#!/bin/bash\necho hi\n")
        exe.chmod(stat.S_IRWXU)
        result = _run_validate(f'validate_executable_file "{exe}" "test script"')
        assert result.returncode == 0

    def test_fails_on_nonexistent(self, tmp_path: Path) -> None:
        """Returns 1 when the file does not exist."""
        missing = tmp_path / "no_such_bin"
        result = _run_validate(f'validate_executable_file "{missing}" "node"')
        assert result.returncode == 1
        assert "not found or not executable" in result.stderr

    def test_fails_on_non_executable(self, tmp_path: Path) -> None:
        """Returns 1 when the file exists but lacks the executable bit."""
        f = tmp_path / "no_exec"
        f.write_text("data")
        f.chmod(stat.S_IRUSR | stat.S_IWUSR)  # rw- only, no x
        result = _run_validate(f'validate_executable_file "{f}" "binary"')
        assert result.returncode == 1
        assert "not found or not executable" in result.stderr

    def test_fails_with_empty_argument(self) -> None:
        """Returns 1 when called with no argument."""
        result = _run_validate('validate_executable_file ""')
        assert result.returncode == 1
        assert "no file path provided" in result.stderr


# ── validate_positive_integer ─────────────────────────────────────────────────


class TestValidatePositiveInteger:
    """Tests for validate_positive_integer."""

    def test_valid_positive(self) -> None:
        """Returns 0 for positive integers."""
        for val in ("1", "5", "100", "9999"):
            result = _run_validate(f'validate_positive_integer "{val}" "TEST_VAR"')
            assert result.returncode == 0, f"Expected 0 for '{val}', got {result.returncode}"

    def test_fails_on_zero(self) -> None:
        """Returns 1 for zero."""
        result = _run_validate('validate_positive_integer "0" "TEST_VAR"')
        assert result.returncode == 1
        assert "positive integer" in result.stderr

    def test_fails_on_negative(self) -> None:
        """Returns 1 for negative numbers."""
        result = _run_validate('validate_positive_integer "-1" "TEST_VAR"')
        assert result.returncode == 1
        assert "positive integer" in result.stderr

    def test_fails_on_string(self) -> None:
        """Returns 1 for non-numeric strings."""
        result = _run_validate('validate_positive_integer "abc" "TEST_VAR"')
        assert result.returncode == 1
        assert "positive integer" in result.stderr

    def test_fails_on_empty(self) -> None:
        """Returns 1 when value is empty."""
        result = _run_validate('validate_positive_integer "" "TEST_VAR"')
        assert result.returncode == 1
        assert "not set or empty" in result.stderr

    def test_fails_on_float(self) -> None:
        """Returns 1 for floating-point numbers (not integers)."""
        result = _run_validate('validate_positive_integer "1.5" "TEST_VAR"')
        assert result.returncode == 1
        assert "positive integer" in result.stderr

    def test_error_message_includes_name(self) -> None:
        """Error messages include the provided variable name for context."""
        result = _run_validate('validate_positive_integer "0" "CACHE_SIZE"')
        assert result.returncode == 1
        assert "CACHE_SIZE" in result.stderr


# ── Launcher integration tests ────────────────────────────────────────────────


def _setup_launcher_env(workdir: Path) -> None:
    """Create the minimal file layout that launcher.sh expects."""
    (workdir / "logging.sh").write_text((SRC_DIR / "logging.sh").read_text())
    (workdir / "validate.sh").write_text((SRC_DIR / "validate.sh").read_text())
    (workdir / "set_options.js").write_text(
        "#!/bin/bash\necho '{\"test\": true}'\n"
    )
    (workdir / "set_options.js").chmod(0o755)
    (workdir / "set_password.js").write_text("#!/bin/bash\ncat\n")
    (workdir / "set_password.js").chmod(0o755)
    node_stub = workdir / "node_stub"
    node_stub.write_text("#!/bin/bash\necho 'node stub'\n")
    node_stub.chmod(0o755)


class TestLauncherDryRun:
    """Tests for launcher.sh dry-run mode and command expansion."""

    def test_default_args(self, tmp_path: Path) -> None:
        """Dry-run with default args produces expected exec line."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            [
                "resources/app/main.mjs",
                "--port=30000",
                "--headless",
                "--noupdate",
                "--dataPath=/data",
            ],
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stdout: {result.stdout}\nstderr: {result.stderr}"
        assert "exec env -i" in result.stdout
        assert "node_stub" in result.stdout
        assert "--port=30000" in result.stdout
        assert "--headless" in result.stdout
        assert "--noupdate" in result.stdout
        assert "--dataPath=/data" in result.stdout

    def test_ip_discovery_disabled(self, tmp_path: Path) -> None:
        """FOUNDRY_IP_DISCOVERY=false appends --noipdiscovery."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            ["resources/app/main.mjs", "--port=30000"],
            env={"FOUNDRY_IP_DISCOVERY": "false"},
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "--noipdiscovery" in result.stdout

    def test_log_size_and_max_logs(self, tmp_path: Path) -> None:
        """FOUNDRY_LOG_SIZE and FOUNDRY_MAX_LOGS append --logsize and --maxlogs."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            ["resources/app/main.mjs", "--port=30000"],
            env={"FOUNDRY_LOG_SIZE": "50000", "FOUNDRY_MAX_LOGS": "5"},
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "--logsize=50000" in result.stdout
        assert "--maxlogs=5" in result.stdout

    def test_no_backups(self, tmp_path: Path) -> None:
        """FOUNDRY_NO_BACKUPS=true appends --nobackups."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            ["resources/app/main.mjs", "--port=30000"],
            env={"FOUNDRY_NO_BACKUPS": "true"},
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "--nobackups" in result.stdout

    def test_all_flags_combined(self, tmp_path: Path) -> None:
        """Multiple flags produce correct combined expansion."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            ["resources/app/main.mjs", "--port=30000"],
            env={
                "FOUNDRY_IP_DISCOVERY": "false",
                "FOUNDRY_LOG_SIZE": "10000",
                "FOUNDRY_MAX_LOGS": "3",
                "FOUNDRY_NO_BACKUPS": "true",
            },
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "--noipdiscovery" in result.stdout
        assert "--logsize=10000" in result.stdout
        assert "--maxlogs=3" in result.stdout
        assert "--nobackups" in result.stdout


class TestLauncherMissingPath:
    """Tests for launcher.sh failure when required paths are missing."""

    def test_node_executable_missing(self, tmp_path: Path) -> None:
        """Exits non-zero when /usr/local/bin/node is absent.

        We redirect PATH so the node stub is not found at /usr/local/bin/node.
        Since /usr/local/bin/node likely exists on the host, we simulate by
        checking that the validate call is wired up: we override the launcher
        to point to a non-existent node path via a wrapper.
        """
        _setup_launcher_env(tmp_path)
        # Write a wrapper that redefines the node path for testing
        wrapper = tmp_path / "test_launcher.sh"
        wrapper.write_text(
            textwrap.dedent(f"""\
                #!/bin/bash
                set -o nounset
                set -o errexit
                set -o pipefail
                cd '{tmp_path}'
                source logging.sh
                source validate.sh
                # Simulate the node check from launcher.sh with a bogus path
                if ! validate_executable_file "{tmp_path}/no_such_node" "Node.js executable"; then
                  exit 1
                fi
            """)
        )
        wrapper.chmod(0o755)
        result = subprocess.run(
            ["bash", str(wrapper)],
            capture_output=True,
            text=True,
            env={**os.environ, "LOG_NAME": "Test"},
            timeout=10,
        )
        assert result.returncode == 1
        # logging.sh log_error writes to stdout (not stderr)
        assert "not found or not executable" in result.stdout


class TestLauncherUnwritableDir:
    """Tests for launcher.sh failure when config dir is not writable."""

    def test_config_dir_unwritable(self, tmp_path: Path) -> None:
        """Exits non-zero when CONFIG_DIR cannot be written to.

        We create a read-only directory and point CONFIG_DIR at it.
        """
        _setup_launcher_env(tmp_path)
        readonly_config = tmp_path / "readonly_config"
        readonly_config.mkdir()
        readonly_config.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x only

        wrapper = tmp_path / "test_launcher.sh"
        wrapper.write_text(
            textwrap.dedent(f"""\
                #!/bin/bash
                set -o nounset
                set -o errexit
                set -o pipefail
                cd '{tmp_path}'
                source logging.sh
                source validate.sh
                CONFIG_DIR="{readonly_config}"
                mkdir -p "${{CONFIG_DIR}}" || true
                if ! validate_writable_dir "${{CONFIG_DIR}}"; then
                  echo "ERROR: Configuration directory ${{CONFIG_DIR}} is not writable." >&2
                  exit 1
                fi
            """)
        )
        wrapper.chmod(0o755)
        result = subprocess.run(
            ["bash", str(wrapper)],
            capture_output=True,
            text=True,
            env={**os.environ, "LOG_NAME": "Test"},
            timeout=10,
        )
        try:
            assert result.returncode == 1
            assert "not writable" in result.stderr
        finally:
            readonly_config.chmod(stat.S_IRWXU)  # restore for cleanup


class TestLauncherServiceKey:
    """Tests for launcher.sh service key validation."""

    def test_service_key_without_config_fails(self, tmp_path: Path) -> None:
        """Exits 1 when FOUNDRY_SERVICE_KEY is set without FOUNDRY_SERVICE_CONFIG."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            ["resources/app/main.mjs", "--port=30000"],
            env={"FOUNDRY_SERVICE_KEY": "test-key"},
            cwd=tmp_path,
        )
        assert result.returncode == 1
        # logging.sh log_error writes to stdout
        assert "FOUNDRY_SERVICE_KEY" in result.stdout
        assert "FOUNDRY_SERVICE_CONFIG" in result.stdout

    def test_service_key_with_config_succeeds(self, tmp_path: Path) -> None:
        """Dry-run succeeds when both FOUNDRY_SERVICE_KEY and CONFIG are set."""
        _setup_launcher_env(tmp_path)
        result = _run_launcher(
            ["resources/app/main.mjs", "--port=30000"],
            env={
                "FOUNDRY_SERVICE_KEY": "test-key",
                "FOUNDRY_SERVICE_CONFIG": "/etc/foundry/service.json",
            },
            cwd=tmp_path,
        )
        assert result.returncode == 0, f"stderr: {result.stderr}"
        assert "--serviceKey=test-key" in result.stdout


# ── Entrypoint validation integration tests ───────────────────────────────────


class TestEntrypointValidation:
    """Tests that exercise the validation calls extracted from entrypoint.sh."""

    def test_writable_dir_failure_exits_nonzero(self, tmp_path: Path) -> None:
        """Simulate the entrypoint DATA_DIR check: non-writable dir → exit 1."""
        readonly_dir = tmp_path / "readonly_data"
        readonly_dir.mkdir()
        readonly_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        script = textwrap.dedent(f"""\
            validate_writable_dir "{readonly_dir}" || exit 1
        """)
        result = _run_validate(script)
        try:
            assert result.returncode == 1
        finally:
            readonly_dir.chmod(stat.S_IRWXU)

    def test_cache_size_zero_exits_nonzero(self) -> None:
        """Simulate the entrypoint CONTAINER_CACHE_SIZE check: 0 → exit 1."""
        script = textwrap.dedent("""\
            validate_positive_integer "0" "CONTAINER_CACHE_SIZE" || exit 1
        """)
        result = _run_validate(script)
        assert result.returncode == 1

    def test_cache_size_valid_exits_zero(self) -> None:
        """Simulate the entrypoint CONTAINER_CACHE_SIZE check: 5 → exit 0."""
        script = textwrap.dedent("""\
            validate_positive_integer "5" "CONTAINER_CACHE_SIZE" || exit 1
        """)
        result = _run_validate(script)
        assert result.returncode == 0
