"""aeternus login — OAuth 2.0 + PKCE authentication for OpenAI and Anthropic.

OpenAI (Codex CLI OAuth):
  Uses the same client_id as OpenAI's own Codex CLI. Redirect goes to
  http://127.0.0.1:1455/auth/callback — a local server catches the code.
  Works with ChatGPT Plus/Pro subscriptions (same as OpenClaw, Cline, etc.)

Anthropic (Claude):
  Anthropic banned third-party use of subscription OAuth on Jan 9 2026.
  Use ANTHROPIC_API_KEY from console.anthropic.com instead.

Usage:
    aeternus login --provider openai   # OpenAI via ChatGPT subscription
    aeternus login --refresh           # Refresh stored token
"""
import base64
import hashlib
import json
import os
import secrets
import socket
import ssl
import time
import urllib.parse
import urllib.request
import webbrowser
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path
from typing import Optional

import typer

app = typer.Typer(help="Authenticate with OpenAI via OAuth (ChatGPT subscription).")

# ---------------------------------------------------------------------------
# SSL context — macOS Python.org builds don't include system CA certs.
# Use certifi if available, otherwise fall back to system default.
# ---------------------------------------------------------------------------


def _ssl_context() -> ssl.SSLContext:
    try:
        import certifi
        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()

# ---------------------------------------------------------------------------
# Provider constants
# ---------------------------------------------------------------------------

# OpenAI Codex CLI OAuth — same client_id used by OpenClaw, Cline, OpenCode
OPENAI_CLIENT_ID = "app_EMoamEEZ73f0CkXaXp7hrann"
OPENAI_AUTH_URL = "https://auth.openai.com/oauth/authorize"
OPENAI_TOKEN_URL = "https://auth.openai.com/oauth/token"
OPENAI_REDIRECT_PORT = 1455
OPENAI_REDIRECT_URI = f"http://localhost:{OPENAI_REDIRECT_PORT}/auth/callback"
OPENAI_SCOPES = "openid profile email offline_access"

MINIMAX_CLIENT_ID = "78257093-7e40-4613-99e0-527b14b39113"
MINIMAX_CODE_URL = "https://api.minimax.io/oauth/code"
MINIMAX_TOKEN_URL = "https://api.minimax.io/oauth/token"
MINIMAX_SCOPES = "group_id profile model.completion"
MINIMAX_POLL_INTERVAL = 2  # seconds

CREDENTIALS_PATH = Path.home() / ".aeternus" / "credentials.json"
CALLBACK_TIMEOUT = 120  # seconds

# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------


def _pkce_pair() -> tuple[str, str]:
    """Return (code_verifier, code_challenge) using S256 method."""
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    digest = hashlib.sha256(verifier.encode()).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode()
    return verifier, challenge


# ---------------------------------------------------------------------------
# Local callback server (used for OpenAI localhost redirect)
# ---------------------------------------------------------------------------


class _CallbackHandler(BaseHTTPRequestHandler):
    """Captures ?code= from the OAuth redirect, then responds with a close page."""

    code: Optional[str] = None
    error: Optional[str] = None

    def do_GET(self):  # noqa: N802
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)
        if "code" in params:
            _CallbackHandler.code = params["code"][0]
            body = b"<html><body><p>Authentication successful. You may close this tab.</p></body></html>"
        elif "error" in params:
            _CallbackHandler.error = params.get("error_description", params["error"])[0]
            body = b"<html><body><p>Authentication failed. Please retry.</p></body></html>"
        else:
            body = b"<html><body><p>Waiting...</p></body></html>"
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *_):  # suppress server access log
        pass


def _wait_for_code(port: int, timeout: int) -> Optional[str]:
    """Start local server on *port*, wait up to *timeout* seconds for the OAuth code."""
    _CallbackHandler.code = None
    _CallbackHandler.error = None
    server = HTTPServer(("localhost", port), _CallbackHandler)
    server.timeout = 1  # poll every second

    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        server.handle_request()
        if _CallbackHandler.code is not None or _CallbackHandler.error is not None:
            break
    server.server_close()

    if _CallbackHandler.error:
        raise RuntimeError(f"OAuth error: {_CallbackHandler.error}")
    return _CallbackHandler.code


# ---------------------------------------------------------------------------
# Token exchange
# ---------------------------------------------------------------------------


def _exchange_code(
    token_url: str,
    client_id: str,
    code: str,
    code_verifier: str,
    redirect_uri: str,
) -> dict:
    payload = urllib.parse.urlencode(
        {
            "grant_type": "authorization_code",
            "client_id": client_id,
            "code": code,
            "code_verifier": code_verifier,
            "redirect_uri": redirect_uri,
        }
    ).encode()
    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        return json.loads(resp.read())


def _refresh_token_request(token_url: str, client_id: str, refresh_token: str) -> dict:
    payload = urllib.parse.urlencode(
        {
            "grant_type": "refresh_token",
            "client_id": client_id,
            "refresh_token": refresh_token,
        }
    ).encode()
    req = urllib.request.Request(
        token_url,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        return json.loads(resp.read())


# ---------------------------------------------------------------------------
# Credentials store
# ---------------------------------------------------------------------------


def _load_credentials() -> dict:
    if CREDENTIALS_PATH.exists():
        return json.loads(CREDENTIALS_PATH.read_text())
    return {}


def _save_credentials(creds: dict) -> None:
    CREDENTIALS_PATH.parent.mkdir(parents=True, exist_ok=True)
    CREDENTIALS_PATH.write_text(json.dumps(creds, indent=2))


# ---------------------------------------------------------------------------
# .env updater
# ---------------------------------------------------------------------------


def _update_dotenv(key: str, value: str, project_root: Path) -> None:
    """Write or replace *key=value* in .env without touching other lines."""
    env_path = project_root / ".env"
    lines: list[str] = []
    if env_path.exists():
        lines = env_path.read_text().splitlines(keepends=True)

    updated = False
    for i, line in enumerate(lines):
        if line.startswith(f"{key}=") or line.startswith(f"{key} ="):
            lines[i] = f"{key}={value}\n"
            updated = True
            break
    if not updated:
        lines.append(f"{key}={value}\n")

    env_path.write_text("".join(lines))


# ---------------------------------------------------------------------------
# Core OAuth flow (localhost server variant — for OpenAI)
# ---------------------------------------------------------------------------


def _oauth_flow_localhost(
    provider: str,
    client_id: str,
    auth_url: str,
    token_url: str,
    redirect_uri: str,
    redirect_port: int,
    scopes: str,
    extra_params: dict,
    project_root: Path,
) -> dict:
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    params = {
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "scope": scopes,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        **extra_params,
    }
    full_url = auth_url + "?" + urllib.parse.urlencode(params)

    typer.echo(f"\nOpening browser for {provider} login...")
    typer.echo(f"If the browser does not open, visit:\n  {full_url}\n")
    if not webbrowser.open(full_url):
        typer.echo("(Could not open browser automatically — please open the URL above.)")

    typer.echo(f"Waiting for callback on localhost:{redirect_port} (timeout {CALLBACK_TIMEOUT}s)...")
    code = _wait_for_code(redirect_port, CALLBACK_TIMEOUT)
    if not code:
        raise RuntimeError("No authorization code received within timeout.")

    typer.echo("Code received — exchanging for tokens...")
    token_data = _exchange_code(token_url, client_id, code, verifier, redirect_uri)

    access_token = token_data.get("access_token", "")
    refresh_token = token_data.get("refresh_token", "")
    expires_in = token_data.get("expires_in", 3600)
    expires_at = int(time.time()) + int(expires_in)
    scope_list = token_data.get("scope", scopes).split()

    entry: dict = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": expires_at,
        "scopes": scope_list,
    }

    creds = _load_credentials()
    creds[provider] = entry
    _save_credentials(creds)

    env_key = f"{provider.upper()}_AUTH_TOKEN"
    _update_dotenv(env_key, access_token, project_root)

    return entry


# ---------------------------------------------------------------------------
# MiniMax device code flow
# ---------------------------------------------------------------------------


def _minimax_device_flow(project_root: Path) -> dict:
    """MiniMax device code OAuth flow — no browser redirect needed."""
    verifier, challenge = _pkce_pair()
    state = secrets.token_urlsafe(16)

    # Step 1: Request device code
    payload = urllib.parse.urlencode({
        "response_type": "code",
        "client_id": MINIMAX_CLIENT_ID,
        "scope": MINIMAX_SCOPES,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "state": state,
    }).encode()
    req = urllib.request.Request(
        MINIMAX_CODE_URL,
        data=payload,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
        code_data = json.loads(resp.read())

    user_code = code_data["user_code"]
    verification_uri = code_data["verification_uri"]
    expires_at_ts = code_data.get("expired_in", int(time.time()) + 300)
    poll_interval = code_data.get("interval", MINIMAX_POLL_INTERVAL * 1000) / 1000

    typer.echo(f"\nMiniMax authorization required.")
    typer.echo(f"  1. Open this URL in your browser: {verification_uri}")
    typer.echo(f"  2. Enter this code when prompted: {user_code}")
    typer.echo(f"\nWaiting for authorization...")
    if not webbrowser.open(verification_uri):
        typer.echo("  (Could not open browser automatically — please open the URL above.)")

    # Step 2: Poll for token
    while int(time.time()) < expires_at_ts:
        time.sleep(poll_interval)
        poll_payload = urllib.parse.urlencode({
            "grant_type": "urn:ietf:params:oauth:grant-type:user_code",
            "client_id": MINIMAX_CLIENT_ID,
            "user_code": user_code,
            "code_verifier": verifier,
        }).encode()
        poll_req = urllib.request.Request(
            MINIMAX_TOKEN_URL,
            data=poll_payload,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            method="POST",
        )
        try:
            with urllib.request.urlopen(poll_req, timeout=15, context=_ssl_context()) as resp:
                token_data = json.loads(resp.read())
            if "access_token" in token_data:
                break
        except Exception:
            continue  # authorization_pending — keep polling
    else:
        raise RuntimeError("MiniMax authorization timed out.")

    access_token = token_data["access_token"]
    refresh_token = token_data.get("refresh_token", "")
    token_expires_at = token_data.get("expired_in", int(time.time()) + 3600)

    entry = {
        "access_token": access_token,
        "refresh_token": refresh_token,
        "expires_at": token_expires_at,
    }
    creds = _load_credentials()
    creds["minimax"] = entry
    _save_credentials(creds)

    _update_dotenv("MINIMAX_OAUTH_TOKEN", access_token, project_root)
    return entry


# ---------------------------------------------------------------------------
# CLI command
# ---------------------------------------------------------------------------

_PROJECT_ROOT = Path(__file__).parent.parent.parent


@app.callback(invoke_without_command=True)
def login(
    provider: str = typer.Option(
        "openai",
        "--provider",
        "-p",
        help="Provider: 'openai' (ChatGPT subscription OAuth) or 'minimax' (device code flow).",
    ),
    refresh: bool = typer.Option(
        False,
        "--refresh",
        help="Refresh stored token without browser interaction.",
    ),
) -> None:
    """Authenticate with OpenAI or MiniMax via OAuth (no API key needed).

    openai: Uses the same OAuth client as OpenAI's Codex CLI — works with ChatGPT
    Plus/Pro subscriptions.  Stores the token in ~/.aeternus/credentials.json
    and writes OPENAI_AUTH_TOKEN to .env so all aeternus commands pick it up.

    minimax: Uses a device code flow — opens the MiniMax authorization page in
    your browser and polls for the token.  Writes MINIMAX_OAUTH_TOKEN to .env.
    """
    provider = provider.lower()

    if provider == "anthropic":
        typer.echo(
            "[error] Anthropic banned subscription OAuth for third-party tools on Jan 9 2026.\n"
            "        Use ANTHROPIC_API_KEY from console.anthropic.com instead.",
            err=True,
        )
        raise typer.Exit(1)

    if provider not in ("openai", "minimax"):
        typer.echo(f"Unknown provider '{provider}'. Use 'openai' or 'minimax'.", err=True)
        raise typer.Exit(1)

    # --- MiniMax branch ---
    if provider == "minimax":
        if refresh:
            creds = _load_credentials()
            stored = creds.get("minimax", {})
            rt = stored.get("refresh_token")
            if not rt:
                typer.echo(
                    "No stored refresh token for minimax. Run login without --refresh first.",
                    err=True,
                )
                raise typer.Exit(1)

            typer.echo("Refreshing minimax token...")
            try:
                payload = urllib.parse.urlencode({
                    "grant_type": "refresh_token",
                    "client_id": MINIMAX_CLIENT_ID,
                    "refresh_token": rt,
                }).encode()
                req = urllib.request.Request(
                    MINIMAX_TOKEN_URL,
                    data=payload,
                    headers={"Content-Type": "application/x-www-form-urlencoded"},
                    method="POST",
                )
                with urllib.request.urlopen(req, timeout=30, context=_ssl_context()) as resp:
                    token_data = json.loads(resp.read())
            except Exception as exc:
                typer.echo(f"Token refresh failed: {exc}", err=True)
                raise typer.Exit(1)

            stored["access_token"] = token_data.get("access_token", stored["access_token"])
            if "refresh_token" in token_data:
                stored["refresh_token"] = token_data["refresh_token"]
            stored["expires_at"] = token_data.get("expired_in", int(time.time()) + 3600)

            creds["minimax"] = stored
            _save_credentials(creds)
            _update_dotenv("MINIMAX_OAUTH_TOKEN", stored["access_token"], _PROJECT_ROOT)
            typer.echo("[ok] MiniMax token refreshed successfully.")
            return

        try:
            entry = _minimax_device_flow(_PROJECT_ROOT)
        except Exception as exc:
            typer.echo(f"MiniMax login failed: {exc}", err=True)
            raise typer.Exit(1)

        typer.echo(
            f"\n[ok] Logged in to MiniMax."
            f"\n     Credentials saved to: {CREDENTIALS_PATH}"
            f"\n     .env updated with MINIMAX_OAUTH_TOKEN"
        )
        return

    # --- OpenAI branch ---
    client_id = OPENAI_CLIENT_ID
    auth_url = OPENAI_AUTH_URL
    token_url = OPENAI_TOKEN_URL
    redirect_uri = OPENAI_REDIRECT_URI
    redirect_port = OPENAI_REDIRECT_PORT
    scopes = OPENAI_SCOPES

    if refresh:
        creds = _load_credentials()
        stored = creds.get(provider, {})
        rt = stored.get("refresh_token")
        if not rt:
            typer.echo(
                f"No stored refresh token for {provider}. Run login without --refresh first.",
                err=True,
            )
            raise typer.Exit(1)

        typer.echo(f"Refreshing {provider} token...")
        try:
            token_data = _refresh_token_request(token_url, client_id, rt)
        except Exception as exc:
            typer.echo(f"Token refresh failed: {exc}", err=True)
            raise typer.Exit(1)

        stored["access_token"] = token_data.get("access_token", stored["access_token"])
        if "refresh_token" in token_data:
            stored["refresh_token"] = token_data["refresh_token"]
        stored["expires_at"] = int(time.time()) + int(token_data.get("expires_in", 3600))

        creds[provider] = stored
        _save_credentials(creds)
        _update_dotenv("OPENAI_AUTH_TOKEN", stored["access_token"], _PROJECT_ROOT)
        typer.echo("[ok] OpenAI token refreshed successfully.")
        return

    try:
        entry = _oauth_flow_localhost(
            provider=provider,
            client_id=client_id,
            auth_url=auth_url,
            token_url=token_url,
            redirect_uri=redirect_uri,
            redirect_port=redirect_port,
            scopes=scopes,
            extra_params={
                "id_token_add_organizations": "true",
                "codex_cli_simplified_flow": "true",
                "originator": "pi",
            },
            project_root=_PROJECT_ROOT,
        )
    except Exception as exc:
        typer.echo(f"Login failed: {exc}", err=True)
        raise typer.Exit(1)

    expires_dt = time.strftime("%Y-%m-%d %H:%M UTC", time.gmtime(entry["expires_at"]))
    typer.echo(
        f"\n[ok] Logged in to OpenAI."
        f"\n     Token expires: {expires_dt}"
        f"\n     Credentials saved to: {CREDENTIALS_PATH}"
        f"\n     .env updated with OPENAI_AUTH_TOKEN"
    )

    remaining = entry["expires_at"] - int(time.time())
    if remaining < 300:
        typer.echo(f"Warning: token expires in {remaining}s — run 'aeternus login --refresh' soon.")
