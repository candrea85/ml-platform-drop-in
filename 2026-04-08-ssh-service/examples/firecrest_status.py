#!/usr/bin/env python3
"""
Example: authenticate with CSCS and query FirecREST system status.

This script shows how to obtain an OIDC access token and use it to
interact with FirecREST. The same token works with any OIDC-protected
API at the centre (FirecREST, SSH service, etc.).

Two authentication methods are supported:
  - Browser-based OIDC (Authorization Code flow with PKCE)
  - Password grant (username + password + OTP, no browser needed)

Usage:
    # Browser-based login (opens browser for OIDC)
    python firecrest_status.py

    # Password grant (no browser needed)
    python firecrest_status.py --username YOUR_USERNAME --password YOUR_PASSWORD --totp 123456

    # Use TDS environment
    python firecrest_status.py --env tds

Requirements:
    pip install requests
"""

from __future__ import annotations

import argparse
import base64
import getpass
import hashlib
import http.server
import secrets
import sys
import urllib.parse
import webbrowser

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install it with:")
    print("  pip install requests")
    sys.exit(1)


# ---------------------------------------------------------------------------
# Configuration
#
# Each environment defines:
#   - issuer:             Keycloak realm URL, used to discover OIDC endpoints
#   - firecrest_base_url: FirecREST v2 API base URL
#
# The OIDC client "authx-cli" is a public client (no secret required).
# The local redirect server listens on localhost:8765 for the browser flow.
# ---------------------------------------------------------------------------
ENVIRONMENTS = {
    "prod": {
        "issuer": "https://auth.cscs.ch/auth/realms/cscs",
        "firecrest_base_url": "https://api.cscs.ch/ml/firecrest/v2",
    },
    "tds": {
        "issuer": "https://auth-tds.cscs.ch/auth/realms/cscs",
        "firecrest_base_url": "https://api.cscs.ch/ml/firecrest/v2",
    },
}

CLIENT_ID = "authx-cli"
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPES = "openid"


# ---------------------------------------------------------------------------
# PKCE helpers (for browser-based flow)
#
# PKCE (Proof Key for Code Exchange) prevents authorization code interception
# attacks. We generate a random verifier and derive a SHA-256 challenge that
# is sent with the authorization request. The verifier is sent later when
# exchanging the code for a token.
# ---------------------------------------------------------------------------
def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Local HTTP server to catch the OIDC redirect (browser flow)
# ---------------------------------------------------------------------------
class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Temporary HTTP handler for the OIDC redirect.

    After the user logs in, Keycloak redirects the browser to
    http://localhost:REDIRECT_PORT with an authorization code.
    This handler parses the code and state from the URL, stores them
    as class attributes, and returns a success/failure page.
    Content-Length and Connection:close ensure the browser receives the
    full response before the server shuts down.
    """

    auth_code: str | None = None
    state: str | None = None

    def do_GET(self):
        # Extract the authorization code and state from the redirect URL
        params = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
        _OAuthCallbackHandler.auth_code = params.get("code", [None])[0]
        _OAuthCallbackHandler.state = params.get("state", [None])[0]

        # Build the response page shown in the browser
        if _OAuthCallbackHandler.auth_code:
            body = (
                "<html><body style='font-family:system-ui;text-align:center;padding:80px'>"
                "<h1 style='color:#2d8a4e'>&#10003; Authentication successful</h1>"
                "<p>You can close this tab and return to the terminal.</p>"
                "</body></html>"
            )
        else:
            body = (
                "<html><body style='font-family:system-ui;text-align:center;padding:80px'>"
                "<h1 style='color:#d61f26'>Authentication failed</h1>"
                "</body></html>"
            )

        # Send a complete HTTP response with explicit length so the browser
        # does not show a connection-reset error when the server exits
        encoded = body.encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/html")
        self.send_header("Content-Length", str(len(encoded)))
        self.send_header("Connection", "close")
        self.end_headers()
        self.wfile.write(encoded)
        self.wfile.flush()

    def log_message(self, format, *args):
        pass


# ---------------------------------------------------------------------------
# Step 1a: Authenticate via browser (Authorization Code + PKCE)
#
# This is the recommended flow for interactive use:
#   1. Discover OIDC endpoints from the Keycloak well-known URL
#   2. Generate a PKCE code verifier/challenge pair for security
#   3. Open the browser to the Keycloak login page
#   4. Listen on localhost:8765 for the redirect with the auth code
#   5. Exchange the auth code for an access token
# ---------------------------------------------------------------------------
def authenticate_browser(issuer: str) -> str:
    """Authenticate via browser-based OIDC Authorization Code flow with PKCE."""
    # Discover the authorization and token endpoints from Keycloak
    well_known = f"{issuer}/.well-known/openid-configuration"
    print(f"  Discovering OIDC endpoints from {issuer} ...")
    disco = requests.get(well_known, timeout=10).json()
    auth_endpoint = disco["authorization_endpoint"]
    token_endpoint = disco["token_endpoint"]

    # Generate PKCE pair and random state/nonce for CSRF protection
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Build the authorization URL and open the browser
    auth_params = {
        "client_id": CLIENT_ID,
        "response_type": "code",
        "redirect_uri": REDIRECT_URI,
        "scope": SCOPES,
        "state": state,
        "nonce": nonce,
        "code_challenge": code_challenge,
        "code_challenge_method": "S256",
    }
    auth_url = f"{auth_endpoint}?{urllib.parse.urlencode(auth_params)}"

    print("  Opening browser for authentication ...")
    print(f"  (If the browser doesn't open, visit: {auth_url[:80]}...)")
    webbrowser.open(auth_url)

    # Start a temporary local HTTP server and wait for the redirect
    print("  Waiting for authentication (timeout: 2 minutes) ...")
    server = http.server.HTTPServer(
        (REDIRECT_HOST, REDIRECT_PORT), _OAuthCallbackHandler
    )
    server.timeout = 120
    server.handle_request()
    server.server_close()

    auth_code = _OAuthCallbackHandler.auth_code
    if not auth_code:
        print("Error: No authorization code received.")
        sys.exit(1)
    if _OAuthCallbackHandler.state != state:
        print("Error: State mismatch.")
        sys.exit(1)

    # Exchange the authorization code for an access token
    print("  Exchanging authorization code for token ...")
    token_resp = requests.post(
        token_endpoint,
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "code": auth_code,
            "redirect_uri": REDIRECT_URI,
            "code_verifier": code_verifier,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    return token_resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Step 1b: Authenticate via password grant (no browser needed)
#
# A simpler alternative for environments without a browser or for quick tests.
# Requires username, password, and a TOTP code from your authenticator app.
# ---------------------------------------------------------------------------
def authenticate_password(issuer: str, username: str, password: str, totp: str) -> str:
    """Authenticate via Resource Owner Password Credentials grant."""
    # Discover the token endpoint from the Keycloak well-known URL
    well_known = f"{issuer}/.well-known/openid-configuration"
    disco = requests.get(well_known, timeout=10).json()
    token_endpoint = disco["token_endpoint"]

    # Request a token using the password grant type
    print(f"  Requesting token for user {username} ...")
    token_resp = requests.post(
        token_endpoint,
        data={
            "grant_type": "password",
            "client_id": CLIENT_ID,
            "username": username,
            "password": password,
            "totp": totp,
        },
        timeout=30,
    )
    token_resp.raise_for_status()
    return token_resp.json()["access_token"]


# ---------------------------------------------------------------------------
# Step 2: Query FirecREST status
#
# Uses the same Bearer token from Step 1. FirecREST accepts OIDC tokens
# from the same Keycloak realm, so no additional authentication is needed.
# The same approach works with any OIDC-protected API at the centre.
# API docs: https://api.cscs.ch/ml/firecrest/v2/openapi.json
# ---------------------------------------------------------------------------
def firecrest_get_systems(access_token: str, base_url: str) -> dict:
    """Query FirecREST /status/systems to get the list of available systems."""
    url = f"{base_url}/status/systems"
    print(f"  Querying {url} ...")

    response = requests.get(
        url,
        headers={"Authorization": f"Bearer {access_token}"},
        timeout=30,
    )

    if response.status_code == 401:
        print("Error: Access token is invalid or expired.")
        sys.exit(1)

    response.raise_for_status()
    return response.json()


def print_systems_status(systems: list[dict]) -> None:
    """Pretty-print the FirecREST systems status as a table."""
    if not systems:
        print("  No systems found.")
        return

    # Print a formatted table with system name, status, and description
    print(f"\n  {'System':<20} {'Status':<12} {'Description'}")
    print(f"  {'─' * 20} {'─' * 12} {'─' * 40}")

    for system in systems:
        name = system.get("name", system.get("system", "unknown"))
        status = system.get("status", "unknown")
        desc = system.get("description", "")
        # Color the status: green for available, red for anything else
        if status == "available":
            status_str = f"\033[32m{status}\033[0m"
        else:
            status_str = f"\033[31m{status}\033[0m"
        print(f"  {name:<20} {status_str:<21} {desc}")
    print()


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------
def main():
    parser = argparse.ArgumentParser(
        description="Authenticate with CSCS and query FirecREST system status.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s                                                    # browser login
  %(prog)s --username user --password pass --totp 123456      # password grant
  %(prog)s --env tds                                          # use TDS environment
        """,
    )
    parser.add_argument(
        "--env",
        choices=ENVIRONMENTS.keys(),
        default="prod",
        help="Environment (default: prod)",
    )
    parser.add_argument("--username", help="CSCS username (for password grant)")
    parser.add_argument("--password", help="CSCS password (for password grant, prompted if not given)")
    parser.add_argument("--totp", help="OTP code (for password grant)")

    args = parser.parse_args()
    env = ENVIRONMENTS[args.env]

    print("CSCS FirecREST Status")
    print("=" * 50)

    # --- Step 1: Authenticate ---
    # Choose between browser-based OIDC (interactive) or password grant
    # (non-interactive). Both return the same type of OIDC access token
    # that can be used with any OIDC-protected API at the centre.
    print(f"\n[1/2] Authenticating ({args.env}) ...")
    if args.username:
        # Password grant: username + password + OTP, no browser needed
        password = args.password or getpass.getpass("  Password: ")
        totp = args.totp or input("  OTP code: ")
        access_token = authenticate_password(env["issuer"], args.username, password, totp)
    else:
        # Browser flow: opens browser for Keycloak login
        access_token = authenticate_browser(env["issuer"])

    print("  Token obtained.\n")

    # --- Step 2: Query FirecREST ---
    # Use the access token to call the FirecREST status API.
    # The same token works with any OIDC-protected API at the centre
    # (SSH service, FirecREST, etc.) without additional authentication.
    print("[2/2] Querying FirecREST ...")
    systems = firecrest_get_systems(access_token, env["firecrest_base_url"])

    # Handle different response shapes (list or dict with nested list)
    if isinstance(systems, dict):
        systems = systems.get("systems", systems.get("data", [systems]))

    print_systems_status(systems)
    print("Done.")


if __name__ == "__main__":
    main()
