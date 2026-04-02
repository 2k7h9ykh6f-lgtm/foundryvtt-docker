"""Property-based tests for src/backoff.sh using Hypothesis.

Each test is tagged with:
  # Feature: auth-failure-backoff, Property <N>: <property_text>

Requires: hypothesis, pytest
"""

# Standard Python Libraries
import json
import os
from pathlib import Path
import subprocess
import textwrap

# Third-Party Libraries
from hypothesis import given, settings
from hypothesis import strategies as st

SRC_DIR = Path(__file__).parent.parent / "src"

# ── Helper ────────────────────────────────────────────────────────────────────


def compute_delay(n: int) -> int:
    """Mirror the bash formula: n=1 → 0, n>1 → min(10 * 2^(n-2), 960)."""
    if n <= 1:
        return 0
    return min(10 * (2 ** (n - 2)), 960)


LOG_STUBS = textwrap.dedent("""\
    log()       { :; }
    log_debug() { :; }
    log_warn()  { :; }
    log_error() { :; }
""")


def _run(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources backoff.sh with logging stubbed out."""
    full_script = f"cd {SRC_DIR}\n{LOG_STUBS}\nsource backoff.sh\n{script}"
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


# ── Property 1: Backoff delay formula correctness ─────────────────────────────
# Feature: auth-failure-backoff, Property 1: Backoff delay formula correctness


@settings(max_examples=100)
@given(n=st.integers(min_value=1, max_value=20))
def test_delay_formula_correctness(n: int) -> None:
    """For any n >= 1, compute_delay(n) matches the formula.

    (n=1 → 0, n>1 → min(10*2^(n-2), 960)).

    Validates: Requirements 1.2
    """
    # Feature: auth-failure-backoff, Property 1: Backoff delay formula correctness
    expected = 0 if n <= 1 else min(10 * (2 ** (n - 2)), 960)
    assert (
        compute_delay(n) == expected
    ), f"n={n}: expected {expected}, got {compute_delay(n)}"


# ── Property 3: Delay is monotonically non-decreasing and capped ──────────────
# Feature: auth-failure-backoff, Property 3: Delay is monotonically
# non-decreasing and capped


@settings(max_examples=100)
@given(n=st.integers(min_value=1, max_value=50))
def test_delay_monotonic_and_capped(n: int) -> None:
    """delay(n+1) >= delay(n) and delay(n) <= 960 for all n >= 1.

    Validates: Requirements 1.2
    """
    # Feature: auth-failure-backoff, Property 3: Delay is monotonically
    # non-decreasing and capped
    assert compute_delay(n + 1) >= compute_delay(n), (
        f"Monotonicity violated: delay({n + 1})="
        f"{compute_delay(n + 1)} < delay({n})={compute_delay(n)}"
    )
    assert compute_delay(n) <= 960, f"Cap violated: delay({n})={compute_delay(n)} > 960"


# ── Property 2: Failure state round-trip ──────────────────────────────────────
# Feature: auth-failure-backoff, Property 2: Failure state round-trip


@settings(max_examples=50)
@given(failure_count=st.integers(min_value=1, max_value=20))
def test_failure_state_round_trip(tmp_path_factory, failure_count: int) -> None:
    """Writing a failure count to the state file and reading it back.

    Validates: Requirements 1.1, 1.4
    """
    # Feature: auth-failure-backoff, Property 2: Failure state round-trip
    tmp_path = tmp_path_factory.mktemp("roundtrip")

    # Pre-seed the state file so backoff_on_failure starts from failure_count - 1
    # (it increments by 1 internally), giving us failure_count in the output.
    seed_count = failure_count - 1
    if seed_count > 0:
        seed_data = json.dumps(
            {
                "consecutive_failures": seed_count,
                "last_failure_timestamp": "2024-01-01T00:00:00Z",
            }
        )
        (tmp_path / "backoff_state.json").write_text(seed_data)

    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        sleep() {{ :; }}
        export -f sleep
        backoff_on_failure 1
    """)
    _run(script)  # exits with 1, expected

    state_file = tmp_path / "backoff_state.json"
    assert state_file.exists(), "State file must exist after failure"
    data = json.loads(state_file.read_text())
    assert data["consecutive_failures"] == failure_count, (
        f"Round-trip failed: wrote seed {seed_count}, expected {failure_count}, "
        f"got {data['consecutive_failures']}"
    )


# ── Property 4: Kubernetes bypass — no state file access ─────────────────────
# Feature: auth-failure-backoff, Property 4: Kubernetes bypass — no state file access


@settings(max_examples=50)
@given(exit_code=st.integers(min_value=1, max_value=255))
def test_kubernetes_no_state_file(tmp_path_factory, exit_code: int) -> None:
    """In a Kubernetes environment, no state file is created or modified.

    Validates: Requirements 3.2, 3.4
    """
    # Feature: auth-failure-backoff, Property 4: Kubernetes bypass — no state
    # file access
    tmp_path = tmp_path_factory.mktemp("k8s")
    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        backoff_on_failure {exit_code}
    """)
    result = _run(script, env={"KUBERNETES_SERVICE_HOST": "10.0.0.1"})
    assert (
        result.returncode == 0
    ), f"Kubernetes path should return 0, got {result.returncode}"
    assert not (tmp_path / "backoff_state.json").exists(), (
        f"State file must not be created in "
        f"Kubernetes environment (exit_code={exit_code})"
    )


# ── Property 5: Successful startup resets failure count ───────────────────────
# Feature: auth-failure-backoff, Property 5: Successful startup resets failure count


@settings(max_examples=50)
@given(failure_count=st.integers(min_value=1, max_value=20))
def test_successful_startup_resets_state(tmp_path_factory, failure_count: int) -> None:
    """After a successful startup, the state file is absent.

    Validates: Requirements 4.1
    """
    # Feature: auth-failure-backoff, Property 5: Successful startup resets failure count
    tmp_path = tmp_path_factory.mktemp("reset")
    state_file = tmp_path / "backoff_state.json"
    state_file.write_text(
        json.dumps(
            {
                "consecutive_failures": failure_count,
                "last_failure_timestamp": "2024-01-01T00:00:00Z",
            }
        )
    )

    script = textwrap.dedent(f"""\
        CONTAINER_CACHE={tmp_path}
        backoff_reset
    """)
    result = _run(script)
    assert result.returncode == 0, result.stderr
    assert not state_file.exists(), (
        f"State file must be absent after successful "
        f"startup (failure_count={failure_count})"
    )
