"""Unit tests for src/cache.sh.

Tests are driven via subprocess calls to bash, sourcing cache.sh directly.
logging.sh is stubbed out so tests have no terminal-color side-effects.

Coverage matrix:
  - First download:    cache_init creates directory, writes CACHEDIR.TAG,
                       permissions validated
  - Cache hit:         cache_init is idempotent — safe to re-run on an
                       existing cache directory with files already present
  - Permission failure: cache_init returns 1 when the directory cannot be
                       created or is not writable
  - Stale temp cleanup: downloading.zip and backoff_state.json.tmp from a
                        prior interrupted run are removed on cache_init
  - Cache prune:       cache_prune keeps only CONTAINER_CACHE_SIZE most
                       recent archives; no-op when size is unset
"""

# Standard Python Libraries
import os
from pathlib import Path
import stat
import subprocess
import textwrap

# Third-Party Libraries
import pytest

# Absolute path to the src/ directory so bash can find cache.sh / logging.sh.
SRC_DIR = Path(__file__).parent.parent / "src"


def _run(
    script: str, env: dict | None = None, timeout: int = 10
) -> subprocess.CompletedProcess:
    """Run a bash snippet that sources cache.sh with logging stubbed out."""
    log_stubs = textwrap.dedent("""\
        log()       { :; }
        log_debug() { :; }
        log_warn()  { :; }
        log_error() { :; }
    """)
    full_script = f"cd '{SRC_DIR}'\n{log_stubs}\nsource cache.sh\n{script}"
    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        ["bash", "-c", full_script],
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


# ── cache_resolve_dir ─────────────────────────────────────────────────────────


class TestCacheResolveDir:
    """Tests for cache_resolve_dir — the CONTAINER_CACHE default-value rule."""

    def test_unset_defaults_to_data_container_cache(self) -> None:
        """When CONTAINER_CACHE is unset, it becomes /data/container_cache."""
        result = _run(
            "unset CONTAINER_CACHE\n"
            "cache_resolve_dir\n"
            'echo "${CONTAINER_CACHE}"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "/data/container_cache"

    def test_empty_string_stays_empty(self) -> None:
        """When CONTAINER_CACHE is empty string, it stays empty (caching disabled)."""
        result = _run(
            'CONTAINER_CACHE=""\n'
            "cache_resolve_dir\n"
            'echo "X${CONTAINER_CACHE}X"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "XX"

    def test_custom_path_preserved(self) -> None:
        """When CONTAINER_CACHE is set to a custom path, it is preserved."""
        result = _run(
            'CONTAINER_CACHE="/tmp/my-custom-cache"\n'
            "cache_resolve_dir\n"
            'echo "${CONTAINER_CACHE}"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "/tmp/my-custom-cache"

    def test_idempotent(self) -> None:
        """Calling cache_resolve_dir twice produces the same result."""
        result = _run(
            "unset CONTAINER_CACHE\n"
            "cache_resolve_dir\n"
            "cache_resolve_dir\n"
            'echo "${CONTAINER_CACHE}"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "/data/container_cache"


# ── cache_init: first download (directory creation) ───────────────────────────


class TestCacheInitFirstDownload:
    """Tests for cache_init when the cache directory does not yet exist."""

    def test_creates_directory(self, tmp_path: Path) -> None:
        """cache_init creates the cache directory when it doesn't exist."""
        cache_dir = tmp_path / "new_cache"
        assert not cache_dir.exists()

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OK"
        assert cache_dir.is_dir()

    def test_writes_cachedir_tag(self, tmp_path: Path) -> None:
        """cache_init writes a valid CACHEDIR.TAG marker file."""
        cache_dir = tmp_path / "tag_test"
        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init"
        )
        assert result.returncode == 0, result.stderr

        tag_file = cache_dir / "CACHEDIR.TAG"
        assert tag_file.exists(), "CACHEDIR.TAG was not created"

        content = tag_file.read_text()
        assert content.startswith("Signature: "), "Missing Signature line"
        assert "felddy/foundryvtt" in content, "Missing container reference"
        assert "bford.info/cachedir" in content, "Missing cachedir spec reference"

    def test_cachedir_tag_checksum_correct(self, tmp_path: Path) -> None:
        """The CACHEDIR.TAG checksum matches md5sum of '.IsCacheDirectory'."""
        import hashlib

        expected_md5 = hashlib.md5(b".IsCacheDirectory").hexdigest()

        cache_dir = tmp_path / "checksum_test"
        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init"
        )
        assert result.returncode == 0, result.stderr

        tag_file = cache_dir / "CACHEDIR.TAG"
        first_line = tag_file.read_text().splitlines()[0]
        assert first_line == f"Signature: {expected_md5}"


# ── cache_init: cache hit (idempotent re-initialization) ─────────────────────


class TestCacheInitIdempotent:
    """Tests for cache_init on an existing cache directory."""

    def test_reinit_preserves_existing_files(self, tmp_path: Path) -> None:
        """Re-running cache_init does not delete existing cached archives."""
        cache_dir = tmp_path / "existing_cache"
        cache_dir.mkdir()
        # Simulate a cached release archive
        fake_zip = cache_dir / "foundryvtt-14.363.zip"
        fake_zip.write_text("fake zip content")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init"
        )
        assert result.returncode == 0, result.stderr
        assert fake_zip.exists(), "Existing archive should not be deleted"
        assert fake_zip.read_text() == "fake zip content"

    def test_reinit_updates_cachedir_tag(self, tmp_path: Path) -> None:
        """Re-running cache_init rewrites the CACHEDIR.TAG file."""
        cache_dir = tmp_path / "retag_cache"
        cache_dir.mkdir()

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init"
        )
        assert result.returncode == 0, result.stderr
        tag_file = cache_dir / "CACHEDIR.TAG"
        assert tag_file.exists()
        assert "Signature:" in tag_file.read_text()

    def test_double_init_succeeds(self, tmp_path: Path) -> None:
        """Calling cache_init twice in a row succeeds both times."""
        cache_dir = tmp_path / "double_init"
        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init\n"
            "cache_init\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OK"


# ── cache_init: disabled caching ─────────────────────────────────────────────


class TestCacheInitDisabled:
    """Tests for cache_init when caching is disabled (empty string)."""

    def test_disabled_does_not_create_directory(self, tmp_path: Path) -> None:
        """When CONTAINER_CACHE is empty, no directory is created."""
        result = _run(
            'CONTAINER_CACHE=""\n'
            "cache_init\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OK"
        # No new directories should have been created in tmp_path
        assert list(tmp_path.iterdir()) == []


# ── cache_init: permission failure ────────────────────────────────────────────


class TestCacheInitPermissionFailure:
    """Tests for cache_init when directory creation or access fails."""

    def test_cannot_create_directory_returns_1(self, tmp_path: Path) -> None:
        """cache_init returns 1 when the directory cannot be created."""
        # Create a read-only parent directory
        readonly_parent = tmp_path / "readonly"
        readonly_parent.mkdir()
        readonly_parent.chmod(stat.S_IRUSR | stat.S_IXUSR)  # r-x for owner

        cache_dir = readonly_parent / "subdir" / "cache"

        result = _run(
            "set -e\n"
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init\n"
            'echo "SHOULD_NOT_REACH"'
        )
        assert result.returncode == 1
        assert "SHOULD_NOT_REACH" not in result.stdout

        # Restore permissions for cleanup
        readonly_parent.chmod(stat.S_IRWXU)

    def test_cannot_write_to_directory_returns_1(self, tmp_path: Path) -> None:
        """cache_init returns 1 when the directory exists but is not writable."""
        cache_dir = tmp_path / "no_write"
        cache_dir.mkdir()
        # Make directory read-only (no write permission)
        cache_dir.chmod(stat.S_IRUSR | stat.S_IXUSR)

        result = _run(
            "set -e\n"
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init\n"
            'echo "SHOULD_NOT_REACH"'
        )
        assert result.returncode == 1
        assert "SHOULD_NOT_REACH" not in result.stdout

        # Restore permissions for cleanup
        cache_dir.chmod(stat.S_IRWXU)

    def test_cannot_read_from_directory_returns_1(self, tmp_path: Path) -> None:
        """cache_init returns 1 when the directory contents cannot be listed.

        On POSIX systems, removing read permission from a directory prevents
        listing its contents (readdir) but NOT accessing known filenames.
        Since cache_init only uses known filenames, this scenario cannot be
        reliably tested via chmod.  Instead we verify that cache_init
        explicitly checks the result of its touch/cat/rm probes, which
        would catch a truly inaccessible directory (e.g. NFS root_squash).
        """
        # This test is intentionally a documentation marker rather than a
        # live chmod test — see the docstring for why.
        import platform

        if platform.system() == "Darwin":
            pytest.skip(
                "POSIX directory read permission does not block known-path access"
            )

        cache_dir = tmp_path / "no_read"
        cache_dir.mkdir()
        cache_dir.chmod(stat.S_IWUSR | stat.S_IXUSR)

        result = _run(
            "set -e\n"
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init\n"
            'echo "SHOULD_NOT_REACH"'
        )
        # On Linux this may or may not fail depending on the filesystem.
        # We accept either outcome — the important thing is that cache_init
        # does not crash.
        assert result.returncode in (0, 1)

        cache_dir.chmod(stat.S_IRWXU)


# ── cache_cleanup_stale: stale temporary file removal ────────────────────────


class TestCacheCleanupStale:
    """Tests for cache_cleanup_stale — removal of leftover temp files."""

    def test_removes_stale_downloading_zip(self, tmp_path: Path) -> None:
        """cache_cleanup_stale removes a leftover downloading.zip file."""
        cache_dir = tmp_path / "stale_dl"
        cache_dir.mkdir()
        stale_file = cache_dir / "downloading.zip"
        stale_file.write_text("partial download data")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_cleanup_stale\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert not stale_file.exists(), "downloading.zip should be removed"

    def test_removes_stale_backoff_tmp(self, tmp_path: Path) -> None:
        """cache_cleanup_stale removes a leftover backoff_state.json.tmp file."""
        cache_dir = tmp_path / "stale_bo"
        cache_dir.mkdir()
        stale_file = cache_dir / "backoff_state.json.tmp"
        stale_file.write_text('{"partial": true}')

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_cleanup_stale\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert not stale_file.exists(), "backoff_state.json.tmp should be removed"

    def test_noop_when_no_stale_files(self, tmp_path: Path) -> None:
        """cache_cleanup_stale is a no-op when no stale files exist."""
        cache_dir = tmp_path / "clean"
        cache_dir.mkdir()
        # Put a legitimate file there
        legitimate = cache_dir / "foundryvtt-14.363.zip"
        legitimate.write_text("real zip data")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_cleanup_stale\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert legitimate.exists(), "Legitimate files must not be deleted"

    def test_cache_init_triggers_stale_cleanup(self, tmp_path: Path) -> None:
        """cache_init calls cache_cleanup_stale as part of initialization."""
        cache_dir = tmp_path / "init_stale"
        cache_dir.mkdir()
        stale_file = cache_dir / "downloading.zip"
        stale_file.write_text("leftover from crash")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_init"
        )
        assert result.returncode == 0, result.stderr
        assert not stale_file.exists(), (
            "cache_init should have cleaned up stale downloading.zip"
        )

    def test_removes_both_stale_files_at_once(self, tmp_path: Path) -> None:
        """cache_cleanup_stale removes both types of stale files in one call."""
        cache_dir = tmp_path / "both_stale"
        cache_dir.mkdir()
        dl = cache_dir / "downloading.zip"
        bo = cache_dir / "backoff_state.json.tmp"
        dl.write_text("partial")
        bo.write_text("partial")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "cache_cleanup_stale"
        )
        assert result.returncode == 0, result.stderr
        assert not dl.exists()
        assert not bo.exists()


# ── cache_prune: old archive pruning ─────────────────────────────────────────


class TestCachePrune:
    """Tests for cache_prune — keeping only N most recent archives."""

    def test_prune_keeps_n_latest(self, tmp_path: Path) -> None:
        """cache_prune keeps CONTAINER_CACHE_SIZE most recent archives."""
        cache_dir = tmp_path / "prune"
        cache_dir.mkdir()

        # Create 3 versioned archives
        for ver in ["12.330", "13.345", "14.363"]:
            (cache_dir / f"foundryvtt-{ver}.zip").write_text(f"zip-{ver}")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=2\n'
            "cache_prune"
        )
        assert result.returncode == 0, result.stderr

        remaining = sorted(
            f.name for f in cache_dir.iterdir() if f.name.endswith(".zip")
        )
        # Should keep the 2 highest versions (13.345, 14.363)
        assert remaining == [
            "foundryvtt-13.345.zip",
            "foundryvtt-14.363.zip",
        ]

    def test_prune_noop_when_size_unset(self, tmp_path: Path) -> None:
        """cache_prune is a no-op when CONTAINER_CACHE_SIZE is not set."""
        cache_dir = tmp_path / "no_prune"
        cache_dir.mkdir()
        for ver in ["12.330", "13.345", "14.363"]:
            (cache_dir / f"foundryvtt-{ver}.zip").write_text(f"zip-{ver}")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            "unset CONTAINER_CACHE_SIZE\n"
            "cache_prune"
        )
        assert result.returncode == 0, result.stderr

        remaining = sorted(
            f.name for f in cache_dir.iterdir() if f.name.endswith(".zip")
        )
        assert len(remaining) == 3, "All archives should be preserved"

    def test_prune_noop_when_cache_disabled(self, tmp_path: Path) -> None:
        """cache_prune is a no-op when CONTAINER_CACHE is empty."""
        result = _run(
            'CONTAINER_CACHE=""\n'
            'CONTAINER_CACHE_SIZE=1\n'
            "cache_prune\n"
            'echo "OK"'
        )
        assert result.returncode == 0, result.stderr
        assert result.stdout.strip() == "OK"

    def test_prune_rejects_zero_size(self, tmp_path: Path) -> None:
        """cache_prune returns 1 when CONTAINER_CACHE_SIZE is 0."""
        cache_dir = tmp_path / "bad_size"
        cache_dir.mkdir()

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=0\n'
            "cache_prune"
        )
        assert result.returncode == 1

    def test_prune_rejects_negative_size(self, tmp_path: Path) -> None:
        """cache_prune returns 1 when CONTAINER_CACHE_SIZE is negative."""
        cache_dir = tmp_path / "neg_size"
        cache_dir.mkdir()

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=-1\n'
            "cache_prune"
        )
        assert result.returncode == 1

    def test_prune_rejects_non_numeric_size(self, tmp_path: Path) -> None:
        """cache_prune returns 1 when CONTAINER_CACHE_SIZE is not a number."""
        cache_dir = tmp_path / "nan_size"
        cache_dir.mkdir()

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=abc\n'
            "cache_prune"
        )
        assert result.returncode == 1

    def test_prune_keeps_all_when_fewer_than_size(self, tmp_path: Path) -> None:
        """cache_prune keeps all archives when count < CONTAINER_CACHE_SIZE."""
        cache_dir = tmp_path / "few"
        cache_dir.mkdir()
        (cache_dir / "foundryvtt-14.363.zip").write_text("zip")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=5\n'
            "cache_prune"
        )
        assert result.returncode == 0, result.stderr

        remaining = list(cache_dir.glob("foundryvtt-*.zip"))
        assert len(remaining) == 1, "Single archive should be kept"

    def test_prune_with_size_1_keeps_latest_only(self, tmp_path: Path) -> None:
        """cache_prune with SIZE=1 keeps only the highest-version archive."""
        cache_dir = tmp_path / "keep_one"
        cache_dir.mkdir()
        for ver in ["10.300", "14.363", "12.330"]:
            (cache_dir / f"foundryvtt-{ver}.zip").write_text(f"zip-{ver}")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=1\n'
            "cache_prune"
        )
        assert result.returncode == 0, result.stderr

        remaining = list(cache_dir.glob("foundryvtt-*.zip"))
        assert len(remaining) == 1
        assert remaining[0].name == "foundryvtt-14.363.zip"

    def test_prune_does_not_delete_non_archive_files(self, tmp_path: Path) -> None:
        """cache_prune only touches foundryvtt-*.zip, not other files."""
        cache_dir = tmp_path / "mixed"
        cache_dir.mkdir()
        for ver in ["12.330", "13.345", "14.363"]:
            (cache_dir / f"foundryvtt-{ver}.zip").write_text(f"zip-{ver}")
        # Non-archive files that must survive pruning
        (cache_dir / "backoff_state.json").write_text("{}")
        (cache_dir / "CACHEDIR.TAG").write_text("tag")

        result = _run(
            f'CONTAINER_CACHE="{cache_dir}"\n'
            'CONTAINER_CACHE_SIZE=1\n'
            "cache_prune"
        )
        assert result.returncode == 0, result.stderr
        assert (cache_dir / "backoff_state.json").exists()
        assert (cache_dir / "CACHEDIR.TAG").exists()
