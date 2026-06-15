"""Tests for the unified retry-chain error classification.

Validates the three core scenarios:
  1. Success — backoff state is reset.
  2. Retryable failure (exit 1) — backoff state is created/incremented.
  3. Non-retryable auth failure (exit 2) — backoff is skipped entirely.

All tests run locally via subprocess (no Docker required).
"""

# Standard Python Libraries
import json
import os
from pathlib import Path
import subprocess
import textwrap

# Third-Party Libraries
import pytest

# Absolute path to the src/ directory so bash can find backoff.sh / logging.sh.
SRC_DIR = Path(__file__).parent.parent / "src"

# Stub out logging functions so tests produce no terminal side-effects,
# except log_warn which we capture to verify [NON_RETRYABLE] / [RETRYABLE] tags.
LOG_STUBS = textwrap.dedent("""\
    log()       { :; }
    log_debug() { :; }
    log_warn()  { echo "[WARN] $*" >&2; }
    log_error() { echo "[ERROR] $*" >&2; }
""")


def _run(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources backoff.sh with logging partially stubbed."""
    full_script = f"cd '{SRC_DIR}'\n{LOG_STUBS}\nsource backoff.sh\n{script}"
    merged_env = {**os.environ, **(env or {})}
    merged_env.pop("KUBERNETES_SERVICE_HOST", None)
    if env and "KUBERNETES_SERVICE_HOST" in env:
        merged_env["KUBERNETES_SERVICE_HOST"] = env["KUBERNETES_SERVICE_HOST"]
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


# ── Scenario 1: Success resets backoff state ─────────────────────────────────


def test_success_resets_backoff_state(tmp_path: Path) -> None:
    """After a successful startup, backoff_reset removes the state file.

    Simulates a container that previously failed 3 times, then starts
    successfully.  The state file must be deleted so the next failure
    restarts the backoff sequence from scratch.
    """
    state_file = tmp_path / "backoff_state.json"
    state_file.write_text(
        json.dumps(
            {
                "consecutive_failures": 3,
                "last_failure_timestamp": "2024-01-01T00:00:00Z",
            }
        )
    )

    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        backoff_reset
    """)
    result = _run(script)

    assert result.returncode == 0, f"Expected exit 0, got {result.returncode}"
    assert not state_file.exists(), "State file must be deleted after successful startup"


# ── Scenario 2: Retryable failure applies backoff ────────────────────────────


def test_retryable_failure_creates_state(tmp_path: Path) -> None:
    """Exit code 1 (retryable) creates a state file and increments the counter.

    First failure: consecutive_failures=1, delay=0 (exits immediately).
    Second failure: consecutive_failures=2, delay=10s.
    """
    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        sleep() {{ :; }}
        export -f sleep
        backoff_on_failure 1
    """)

    # First failure
    result = _run(script)
    assert result.returncode == 1, f"Expected exit 1, got {result.returncode}"

    state_file = tmp_path / "backoff_state.json"
    assert state_file.exists(), "State file must be created for retryable failure"
    data = json.loads(state_file.read_text())
    assert data["consecutive_failures"] == 1

    # Verify [RETRYABLE] tag appears in log output
    assert "[RETRYABLE]" in result.stderr, (
        f"Expected [RETRYABLE] tag in stderr, got: {result.stderr}"
    )

    # Second failure — counter increments
    result2 = _run(script)
    assert result2.returncode == 1
    data2 = json.loads(state_file.read_text())
    assert data2["consecutive_failures"] == 2


# ── Scenario 3: Non-retryable auth failure skips backoff ─────────────────────


def test_non_retryable_auth_failure_skips_backoff(tmp_path: Path) -> None:
    """Exit code 2 (non-retryable) exits immediately without creating a state file.

    This simulates a bad-credentials scenario where retrying is pointless.
    The operator must fix their FOUNDRY_USERNAME / FOUNDRY_PASSWORD.
    """
    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        sleep() {{ :; }}
        export -f sleep
        backoff_on_failure 2
    """)

    result = _run(script)

    assert result.returncode == 2, f"Expected exit 2, got {result.returncode}"

    state_file = tmp_path / "backoff_state.json"
    assert not state_file.exists(), (
        "State file must NOT be created for non-retryable failure (exit code 2)"
    )

    # Verify [NON_RETRYABLE] tag appears in log output
    assert "[NON_RETRYABLE]" in result.stderr, (
        f"Expected [NON_RETRYABLE] tag in stderr, got: {result.stderr}"
    )


def test_non_retryable_does_not_increment_existing_state(tmp_path: Path) -> None:
    """If a state file already exists, a non-retryable failure must not touch it.

    This covers the edge case where a retryable failure occurred first (creating
    a state file), and then the next failure is non-retryable.  The state file
    must remain unchanged so that if the operator fixes their credentials and the
    next failure is retryable again, the backoff sequence resumes correctly.
    """
    state_file = tmp_path / "backoff_state.json"
    original_data = {
        "consecutive_failures": 2,
        "last_failure_timestamp": "2024-06-01T12:00:00Z",
    }
    state_file.write_text(json.dumps(original_data))

    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        sleep() {{ :; }}
        export -f sleep
        backoff_on_failure 2
    """)
    result = _run(script)

    assert result.returncode == 2
    # State file must be untouched
    assert state_file.exists(), "State file should still exist (untouched)"
    data = json.loads(state_file.read_text())
    assert data == original_data, (
        f"State file was modified by non-retryable failure: {data}"
    )
