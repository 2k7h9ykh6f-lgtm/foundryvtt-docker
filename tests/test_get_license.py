"""Unit tests for src/get_license.ts (compiled to dist/get_license.js).

Tests verify the exit-code classification and log-prefix convention:
  - exit 0: success (license key printed to stdout)
  - exit 1: retriable (network/5xx) — log contains [RETRY]
  - exit 2: fatal auth (bad cookies, 4xx) — log contains [FATAL_AUTH]
  - exit 3: fatal config (no keys on account) — log contains [FATAL_CONFIG]

These tests exercise the compiled JavaScript via subprocess.

For HTTP-level tests (4xx, 5xx, empty response) we run a tiny HTTP CONNECT
proxy in-process.  The proxy terminates TLS with a self-signed certificate
and returns a configurable mock response, so get_license.js believes it is
talking to foundryvtt.com.  This exercises the full fetchLicenses() path
without touching the real network.
"""

# Standard Python Libraries
import http.server
import json
import os
from pathlib import Path
import socket
import socketserver
import ssl
import subprocess
import tempfile
import threading

# Third-Party Libraries
import pytest

# Absolute path to the dist/ directory (compiled JS output).
DIST_DIR = Path(__file__).parent.parent / "dist"


def _run_get_license(
    cookiejar_path: str,
    extra_args: list[str] | None = None,
    env: dict | None = None,
    timeout: int = 15,
) -> subprocess.CompletedProcess:
    """Run the compiled get_license.js with the given cookie jar."""
    node_bin = "node"
    script = str(DIST_DIR / "get_license.js")
    cmd = [node_bin, script, "--log-level=debug"]
    if extra_args:
        cmd.extend(extra_args)
    cmd.append(cookiejar_path)

    merged_env = {**os.environ, **(env or {})}
    return subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        env=merged_env,
        timeout=timeout,
    )


def _make_cookiejar(path: Path, cookies: list[dict]) -> str:
    """Create a tough-cookie-file-store JSON file at *path*.

    Each item in *cookies* should have keys: key, value, domain, path.
    Returns the path as a string.
    """
    store: dict = {}
    for c in cookies:
        domain = c["domain"]
        cookie_path = c.get("path", "/")
        key = c["key"]
        value = c["value"]

        if domain not in store:
            store[domain] = {}
        if cookie_path not in store[domain]:
            store[domain][cookie_path] = {}
        store[domain][cookie_path][key] = {
            "key": key,
            "value": value,
            "domain": domain,
            "path": cookie_path,
            "secure": False,
            "httpOnly": False,
            "hostOnly": False,
            "creation": "2024-01-01T00:00:00.000Z",
            "lastAccessed": "2024-01-01T00:00:00.000Z",
        }

    path.write_text(json.dumps(store))
    return str(path)


# ── Cookie validation (FATAL_AUTH, exit 2) ──────────────────────────────────


def test_cookie_jar_empty_exits_fatal_auth(tmp_path: Path) -> None:
    """An empty cookie jar (0 cookies for felddy.com) exits with code 2.

    The error log should contain [FATAL_AUTH] to classify this as a
    credential/cookie problem that the operator must fix.
    """
    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(jar_path, [])  # no cookies at all

    result = _run_get_license(str(jar_path))
    assert result.returncode == 2, (
        f"Expected exit 2 (FATAL_AUTH), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "[FATAL_AUTH]" in result.stderr, (
        "Expected [FATAL_AUTH] tag in log output. "
        f"stderr: {result.stderr}"
    )


def test_cookie_jar_wrong_count_exits_fatal_auth(tmp_path: Path) -> None:
    """Two cookies for felddy.com also triggers FATAL_AUTH (expected exactly 1)."""
    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(
        jar_path,
        [
            {"key": "username", "value": "alice", "domain": "felddy.com"},
            {"key": "other", "value": "x", "domain": "felddy.com"},
        ],
    )

    result = _run_get_license(str(jar_path))
    assert result.returncode == 2, (
        f"Expected exit 2, got {result.returncode}. stderr: {result.stderr}"
    )
    assert "[FATAL_AUTH]" in result.stderr


def test_cookie_jar_nonexistent_file_exits_nonzero(tmp_path: Path) -> None:
    """A nonexistent cookie jar file causes a non-zero exit (file I/O error)."""
    fake_path = str(tmp_path / "does_not_exist.json")
    result = _run_get_license(fake_path)
    assert result.returncode != 0, "Should exit non-zero for missing file"


# ── Network error (RETRY, exit 1) ───────────────────────────────────────────


def _find_unused_port() -> int:
    """Find a TCP port that nothing is listening on."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def test_network_error_exits_retry(tmp_path: Path) -> None:
    """When the HTTP connection is refused, exit code is 1 (RETRY).

    We create a valid cookie jar (1 cookie for felddy.com) so the script
    gets past cookie validation, then the fetch to foundryvtt.com fails
    because we route HTTPS through an unused local port.
    """
    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(
        jar_path,
        [{"key": "username", "value": "testuser", "domain": "felddy.com"}],
    )

    # Route HTTPS through a port that nothing listens on.
    # The ProxyAgent used by get_license.js respects HTTPS_PROXY.
    unused_port = _find_unused_port()
    env = {"HTTPS_PROXY": f"http://127.0.0.1:{unused_port}"}

    result = _run_get_license(str(jar_path), env=env)
    assert result.returncode == 1, (
        f"Expected exit 1 (RETRY) for connection refused, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "[RETRY]" in result.stderr, (
        f"Expected [RETRY] tag in log output. stderr: {result.stderr}"
    )


# ── Self-signed HTTPS CONNECT proxy for HTTP-level mock tests ───────────────

# Generate a self-signed certificate at import time so the fixture can use it.
# The certificate is for "foundryvtt.com" (Subject Alternative Name).

_SELF_SIGNED_CERT: str | None = None
_SELF_SIGNED_KEY: str | None = None


def _generate_self_signed_cert(tmpdir: Path) -> tuple[str, str]:
    """Generate a self-signed cert for foundryvtt.com.  Returns (cert_path, key_path)."""
    cert_path = str(tmpdir / "cert.pem")
    key_path = str(tmpdir / "key.pem")

    # Use openssl to generate the cert.  This is available on all major platforms.
    subprocess.run(
        [
            "openssl",
            "req",
            "-x509",
            "-newkey",
            "rsa:2048",
            "-keyout",
            key_path,
            "-out",
            cert_path,
            "-days",
            "1",
            "-nodes",
            "-subj",
            "/CN=foundryvtt.com",
            "-addext",
            "subjectAltName=DNS:foundryvtt.com",
        ],
        capture_output=True,
        check=True,
    )
    return cert_path, key_path


class _MockConnectProxy(http.server.HTTPServer):
    """HTTP server that handles CONNECT requests by terminating TLS and
    returning a configurable mock HTTP response.

    Usage:
        server = _MockConnectProxy(("127.0.0.1", 0), cert_path, key_path,
                                    status=200, body="<html>...</html>")
        port = server.server_address[1]
        # Point HTTPS_PROXY at http://127.0.0.1:{port}
    """

    def __init__(self, addr, cert_path, key_path, status=200, body=""):
        self.cert_path = cert_path
        self.key_path = key_path
        self.mock_status = status
        self.mock_body = body
        super().__init__(addr, _ConnectProxyHandler)


class _ConnectProxyHandler(http.server.BaseHTTPRequestHandler):
    """Handle HTTP CONNECT by upgrading to TLS and serving a mock response."""

    def do_CONNECT(self):  # noqa: N802
        """Handle CONNECT: establish TLS, then serve mock HTTP response."""
        # Send 200 Connection Established
        self.send_response(200)
        self.end_headers()

        # Upgrade the socket to TLS
        context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        context.load_cert_chain(
            self.server.cert_path, self.server.key_path  # type: ignore[attr-defined]
        )
        tls_socket = context.wrap_socket(self.request, server_side=True)

        # Read the HTTP request over TLS
        tls_file = tls_socket.makefile("rb")
        try:
            request_line = tls_file.readline()
            if not request_line:
                return
            # Read headers (consume them)
            while True:
                line = tls_file.readline()
                if not line or line in (b"\r\n", b"\n"):
                    break

            # Send mock HTTP response
            status = self.server.mock_status  # type: ignore[attr-defined]
            body = self.server.mock_body  # type: ignore[attr-defined]
            if isinstance(body, str):
                body = body.encode()
            status_text = {200: "OK", 403: "Forbidden", 503: "Service Unavailable"}.get(
                status, "Error"
            )
            response = (
                f"HTTP/1.1 {status} {status_text}\r\n"
                f"Content-Type: text/html; charset=utf-8\r\n"
                f"Content-Length: {len(body)}\r\n"
                f"Connection: close\r\n"
                f"\r\n"
            ).encode() + body
            tls_socket.sendall(response)
        finally:
            tls_file.close()
            tls_socket.close()

    def log_message(self, format, *args):
        pass  # Suppress logging


@pytest.fixture()
def mock_https_proxy(tmp_path):
    """Fixture that yields (proxy_url, set_response(status, body)).

    Starts a mock HTTPS CONNECT proxy on a random port.  The proxy
    terminates TLS with a self-signed certificate and returns configurable
    mock HTTP responses.

    Returns:
        A tuple of (proxy_url: str, set_response: Callable[[int, str], None]).
        Set HTTPS_PROXY=proxy_url and NODE_EXTRA_CA_CERTS=<cert_path> in the
        subprocess environment.
    """
    cert_path, key_path = _generate_self_signed_cert(tmp_path)

    server = _MockConnectProxy(
        ("127.0.0.1", 0), cert_path, key_path, status=200, body=""
    )
    port = server.server_address[1]
    proxy_url = f"http://127.0.0.1:{port}"

    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()

    def set_response(status: int, body: str):
        server.mock_status = status
        server.mock_body = body

    yield proxy_url, set_response, cert_path

    server.shutdown()


def test_http_200_no_licenses_exits_fatal_config(
    tmp_path: Path, mock_https_proxy
) -> None:
    """Server returns 200 with valid HTML but no license elements → exit 3.

    Validates: FATAL_CONFIG path when account has no associated license keys.
    """
    proxy_url, set_response, cert_path = mock_https_proxy

    # HTML page with no license key elements
    set_response(
        200,
        "<html><body><h1>Community</h1><p>No licenses here.</p></body></html>",
    )

    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(
        jar_path,
        [{"key": "username", "value": "testuser", "domain": "felddy.com"}],
    )

    env = {
        "HTTPS_PROXY": proxy_url,
        "NODE_EXTRA_CA_CERTS": cert_path,
    }

    result = _run_get_license(str(jar_path), env=env)
    assert result.returncode == 3, (
        f"Expected exit 3 (FATAL_CONFIG) for no licenses, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "[FATAL_CONFIG]" in result.stderr, (
        f"Expected [FATAL_CONFIG] tag. stderr: {result.stderr}"
    )


def test_http_503_exits_retry(tmp_path: Path, mock_https_proxy) -> None:
    """Server returns 503 Service Unavailable → exit 1 (RETRY).

    Validates: retriable HTTP error classification.
    """
    proxy_url, set_response, cert_path = mock_https_proxy

    set_response(503, "Service Unavailable")

    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(
        jar_path,
        [{"key": "username", "value": "testuser", "domain": "felddy.com"}],
    )

    env = {
        "HTTPS_PROXY": proxy_url,
        "NODE_EXTRA_CA_CERTS": cert_path,
    }

    result = _run_get_license(str(jar_path), env=env)
    assert result.returncode == 1, (
        f"Expected exit 1 (RETRY) for HTTP 503, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "[RETRY]" in result.stderr, (
        f"Expected [RETRY] tag. stderr: {result.stderr}"
    )


def test_http_403_exits_fatal_auth(tmp_path: Path, mock_https_proxy) -> None:
    """Server returns 403 Forbidden → exit 2 (FATAL_AUTH).

    Validates: non-retriable HTTP 4xx classification.
    """
    proxy_url, set_response, cert_path = mock_https_proxy

    set_response(403, "Forbidden")

    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(
        jar_path,
        [{"key": "username", "value": "testuser", "domain": "felddy.com"}],
    )

    env = {
        "HTTPS_PROXY": proxy_url,
        "NODE_EXTRA_CA_CERTS": cert_path,
    }

    result = _run_get_license(str(jar_path), env=env)
    assert result.returncode == 2, (
        f"Expected exit 2 (FATAL_AUTH) for HTTP 403, got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    assert "[FATAL_AUTH]" in result.stderr, (
        f"Expected [FATAL_AUTH] tag. stderr: {result.stderr}"
    )


def test_http_200_with_license_exits_success(
    tmp_path: Path, mock_https_proxy
) -> None:
    """Server returns 200 with a valid license key → exit 0, key on stdout.

    Validates: the success path.
    """
    proxy_url, set_response, cert_path = mock_https_proxy

    # HTML page with a license key element matching the CSS selector
    # used by get_license.ts: "div.license label.copy input"
    set_response(
        200,
        """<html><body>
        <div class="license">
          <label class="copy">
            <input value="aaaa-bbbb-cccc-dddd-eeee-ffff" />
          </label>
        </div>
        </body></html>""",
    )

    jar_path = tmp_path / "cookies.json"
    _make_cookiejar(
        jar_path,
        [{"key": "username", "value": "testuser", "domain": "felddy.com"}],
    )

    env = {
        "HTTPS_PROXY": proxy_url,
        "NODE_EXTRA_CA_CERTS": cert_path,
    }

    result = _run_get_license(str(jar_path), env=env)
    assert result.returncode == 0, (
        f"Expected exit 0 (SUCCESS), got {result.returncode}. "
        f"stderr: {result.stderr}"
    )
    # License key should have dashes stripped
    assert "aaaabbbbccccddddeeeeffff" in result.stdout, (
        f"Expected license key on stdout. stdout: {result.stdout}"
    )
