#!/usr/bin/env python3
"""
Generate or sign SSH keys using the CSCS HPC SSH service with a standard user account.

Authenticates via browser-based OIDC Authorization Code flow with PKCE
(same flow as the cscs-key CLI). No service account or API Key needed —
just your regular CSCS credentials in the browser.

Usage:
    # Generate a new key pair (opens browser for login)
    python generate_ssh_key_user.py

    # Sign your own public key
    python generate_ssh_key_user.py --sign ~/.ssh/cscs-key.pub

    # Specify duration (default: 1d)
    python generate_ssh_key_user.py --duration 1d

    # Write keys to disk and add to ssh-agent
    python generate_ssh_key_user.py --output ~/.ssh/cscs-key --ssh-add

    # Use TDS (test) environment
    python generate_ssh_key_user.py --env tds

Requirements:
    pip install requests  (or: uv pip install requests)
"""

from __future__ import annotations

import argparse
import base64
import hashlib
import http.server
import json
import os
import secrets
import stat
import subprocess
import sys
import threading
import urllib.parse
import webbrowser
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install it with:")
    print("  pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
ENVIRONMENTS = {
    "prod": {
        "issuer": "https://auth.cscs.ch/auth/realms/cscs",
        "hpc_ssh_base_url": "https://authx-gateway.tds.cscs.ch/api-ssh-service",
    },
    "tds": {
        "issuer": "https://auth-tds.cscs.ch/auth/realms/cscs",
        "hpc_ssh_base_url": "https://api-ssh-service.hpc-ssh.tds.cscs.ch",
    },
}

CLIENT_ID = "authx-cli"
REDIRECT_HOST = "127.0.0.1"
REDIRECT_PORT = 8765
REDIRECT_URI = f"http://localhost:{REDIRECT_PORT}"
SCOPES = "openid"

GENERATE_ENDPOINT = "/api/v1/ssh-keys"
SIGN_ENDPOINT = "/api/v1/ssh-keys/sign"

VALID_DURATIONS = ("1min", "1d")


# ---------------------------------------------------------------------------
# PKCE helpers
# ---------------------------------------------------------------------------
def _generate_pkce() -> tuple[str, str]:
    """Generate PKCE code_verifier and code_challenge (S256)."""
    verifier = secrets.token_urlsafe(64)
    digest = hashlib.sha256(verifier.encode("ascii")).digest()
    challenge = base64.urlsafe_b64encode(digest).rstrip(b"=").decode("ascii")
    return verifier, challenge


# ---------------------------------------------------------------------------
# Local HTTP server to catch the OIDC redirect
# ---------------------------------------------------------------------------
class _OAuthCallbackHandler(http.server.BaseHTTPRequestHandler):
    """Temporary HTTP handler for the OIDC redirect.

    After the user logs in, Keycloak redirects the browser to
    http://localhost:REDIRECT_PORT with an authorization code.
    This handler:
      1. Parses the "code", "state", and "error" query parameters
      2. Stores them as class attributes for the caller to read
      3. Returns a success/failure page to the browser
    Content-Length and Connection:close headers ensure the browser
    receives the full response before the server shuts down.
    """

    auth_code: str | None = None
    state: str | None = None
    error: str | None = None

    def do_GET(self):
        parsed = urllib.parse.urlparse(self.path)
        params = urllib.parse.parse_qs(parsed.query)

        # Extract the authorization code and state from the redirect URL
        _OAuthCallbackHandler.auth_code = params.get("code", [None])[0]
        _OAuthCallbackHandler.state = params.get("state", [None])[0]
        _OAuthCallbackHandler.error = params.get("error", [None])[0]

        # Build the response page shown in the browser
        if _OAuthCallbackHandler.auth_code:
            body = (
                "<html><body style='font-family:system-ui;text-align:center;padding:80px'>"
                "<h1 style='color:#2d8a4e'>&#10003; Authentication successful</h1>"
                "<p>You can close this tab and return to the terminal.</p>"
                "</body></html>"
            )
        else:
            error_desc = params.get("error_description", ["Unknown error"])[0]
            body = (
                "<html><body style='font-family:system-ui;text-align:center;padding:80px'>"
                f"<h1 style='color:#d61f26'>Authentication failed</h1>"
                f"<p>{error_desc}</p>"
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
        pass  # Silence server logs


def _wait_for_auth_code() -> str:
    """Start a local HTTP server on localhost:REDIRECT_PORT, wait for the
    OIDC redirect (up to 2 minutes), and return the authorization code."""
    server = http.server.HTTPServer(
        (REDIRECT_HOST, REDIRECT_PORT), _OAuthCallbackHandler
    )
    server.timeout = 120  # 2 minutes max

    # Handle one request
    server.handle_request()
    server.server_close()

    if _OAuthCallbackHandler.error:
        print(f"Error: OIDC authentication failed: {_OAuthCallbackHandler.error}")
        sys.exit(1)

    code = _OAuthCallbackHandler.auth_code
    if not code:
        print("Error: No authorization code received.")
        sys.exit(1)

    return code


# ---------------------------------------------------------------------------
# Step 1: OIDC Authorization Code flow with PKCE
# ---------------------------------------------------------------------------
def get_access_token(issuer: str) -> str:
    """Authenticate via browser and return an OIDC access token."""

    # Discover endpoints
    well_known = f"{issuer}/.well-known/openid-configuration"
    print(f"  Discovering OIDC endpoints from {issuer} ...")
    disco = requests.get(well_known, timeout=10).json()
    auth_endpoint = disco["authorization_endpoint"]
    token_endpoint = disco["token_endpoint"]

    # Generate PKCE and state
    code_verifier, code_challenge = _generate_pkce()
    state = secrets.token_urlsafe(32)
    nonce = secrets.token_urlsafe(32)

    # Build authorization URL
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

    # Open browser
    print("  Opening browser for authentication ...")
    print(f"  (If the browser doesn't open, visit: {auth_url[:80]}...)")
    webbrowser.open(auth_url)

    # Wait for redirect
    print("  Waiting for authentication (timeout: 2 minutes) ...")
    auth_code = _wait_for_auth_code()

    # Verify state
    if _OAuthCallbackHandler.state != state:
        print("Error: State mismatch — possible CSRF attack.")
        sys.exit(1)

    # Exchange code for token
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
    token_data = token_resp.json()

    access_token = token_data.get("access_token")
    if not access_token:
        print("Error: No access_token in token response.")
        sys.exit(1)

    expires_in = token_data.get("expires_in", "unknown")
    print(f"  Access token obtained (expires in {expires_in}s)")
    return access_token


# ---------------------------------------------------------------------------
# Step 2a: Generate a new SSH key pair
# ---------------------------------------------------------------------------
def generate_ssh_key(
    access_token: str,
    base_url: str,
    duration: str,
    ip_subnets: list[str] | None = None,
    force_command: str | None = None,
) -> dict:
    """Generate a new SSH key pair via the hpc-ssh service."""
    url = f"{base_url}{GENERATE_ENDPOINT}"
    print(f"  Generating SSH key (duration={duration}) ...")

    body: dict = {"duration": duration}
    if ip_subnets:
        body["ipSubnets"] = ip_subnets
    if force_command:
        body["forceCommand"] = force_command

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )

    if response.status_code == 401:
        print("Error: Access token is invalid or expired. Re-run to authenticate.")
        sys.exit(1)

    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Step 2b: Sign an existing public key
# ---------------------------------------------------------------------------
def sign_ssh_key(
    access_token: str,
    base_url: str,
    public_key: str,
    duration: str,
    ip_subnets: list[str] | None = None,
    force_command: str | None = None,
) -> dict:
    """Sign an existing public key via the hpc-ssh service."""
    url = f"{base_url}{SIGN_ENDPOINT}"
    print(f"  Signing public key (duration={duration}) ...")

    body: dict = {"publicKey": public_key, "duration": duration}
    if ip_subnets:
        body["ipSubnets"] = ip_subnets
    if force_command:
        body["forceCommand"] = force_command

    response = requests.post(
        url,
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        json=body,
        timeout=30,
    )

    if response.status_code == 401:
        print("Error: Access token is invalid or expired. Re-run to authenticate.")
        sys.exit(1)

    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Write keys to disk
# ---------------------------------------------------------------------------
def write_keys(output_path: Path, ssh_key: dict, is_sign: bool) -> None:
    """Write SSH key files to disk with correct permissions."""
    cert_path = output_path.with_name(f"{output_path.name}-cert.pub")

    public_key = ssh_key.get("publicKey", "")
    cert_path.write_text(public_key + "\n")
    os.chmod(cert_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)
    print(f"  Certificate written to {cert_path}")

    if not is_sign:
        private_key = ssh_key.get("privateKey", "")
        if private_key:
            output_path.write_text(private_key + "\n")
            os.chmod(output_path, stat.S_IRUSR | stat.S_IWUSR)
            print(f"  Private key written to {output_path}")

    serial = ssh_key.get("serialNumber", "N/A")
    expire = ssh_key.get("expireTime", "N/A")
    fingerprint = ssh_key.get("fingerprint", "N/A")

    print()
    print(f"  Serial number : {serial}")
    print(f"  Expires       : {expire}")
    print(f"  Fingerprint   : {fingerprint}")


# ---------------------------------------------------------------------------
# ssh-add helper
# ---------------------------------------------------------------------------
def add_to_agent(key_path: Path, duration: str) -> None:
    """Add the key to ssh-agent with a matching TTL."""
    ttl_map = {"1min": "60", "1d": "86400"}
    ttl = ttl_map.get(duration, "86400")

    try:
        subprocess.run(["ssh-add", "-t", ttl, str(key_path)], check=True)
        print(f"  Key added to ssh-agent (TTL={ttl}s)")
    except FileNotFoundError:
        print("  Warning: ssh-add not found — key not added to agent")
    except subprocess.CalledProcessError:
        print("  Warning: Failed to add key to ssh-agent")


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------
def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Generate or sign SSH keys via browser-based OIDC login.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --duration 1d --output ~/.ssh/cscs-key --ssh-add
  %(prog)s --sign ~/.ssh/id_ed25519.pub --duration 1d
  %(prog)s --duration 1d --ip-subnets 10.0.0.0/8
        """,
    )
    parser.add_argument(
        "--duration",
        choices=VALID_DURATIONS,
        default="1d",
        help="Key duration (default: 1d)",
    )
    parser.add_argument(
        "--sign",
        metavar="PUBLIC_KEY_FILE",
        help="Path to a public key to sign (instead of generating a new pair)",
    )
    parser.add_argument(
        "--output",
        metavar="PATH",
        help="Write keys to this path (e.g. ~/.ssh/cscs-key)",
    )
    parser.add_argument(
        "--ssh-add",
        action="store_true",
        help="Add the key to ssh-agent after writing",
    )
    parser.add_argument(
        "--ip-subnets",
        nargs="+",
        metavar="CIDR",
        help="Restrict key to specific IP subnets",
    )
    parser.add_argument(
        "--force-command",
        metavar="CMD",
        help="Restrict the key to a specific SSH command",
    )
    parser.add_argument(
        "--env",
        choices=["prod", "tds"],
        default="prod",
        help="Environment (default: prod)",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON response",
    )

    return parser.parse_args()


def main() -> None:
    args = parse_args()
    env = ENVIRONMENTS[args.env]

    print("CSCS SSH Key Generator (User Account — browser login)")
    print("=" * 54)
    print()

    # Step 1: Authenticate via browser
    print("[1/2] Authenticating via browser ...")
    access_token = get_access_token(env["issuer"])
    print()

    # Step 2: Generate or sign
    is_sign = args.sign is not None

    if is_sign:
        pub_key_path = Path(args.sign).expanduser()
        if not pub_key_path.exists():
            print(f"Error: Public key file not found: {pub_key_path}")
            sys.exit(1)
        public_key = pub_key_path.read_text().strip()

        print("[2/2] Signing public key ...")
        result = sign_ssh_key(
            access_token=access_token,
            base_url=env["hpc_ssh_base_url"],
            public_key=public_key,
            duration=args.duration,
            ip_subnets=args.ip_subnets,
            force_command=args.force_command,
        )
    else:
        print("[2/2] Generating SSH key pair ...")
        result = generate_ssh_key(
            access_token=access_token,
            base_url=env["hpc_ssh_base_url"],
            duration=args.duration,
            ip_subnets=args.ip_subnets,
            force_command=args.force_command,
        )

    print()

    ssh_key = result.get("sshKey", {})

    if args.json_output:
        print(json.dumps(result, indent=2))
        return

    if args.output:
        output_path = Path(args.output).expanduser()
        output_path.parent.mkdir(parents=True, exist_ok=True)
        write_keys(output_path, ssh_key, is_sign)

        if args.ssh_add and output_path.exists():
            print()
            add_to_agent(output_path, args.duration)
    else:
        print("SSH Key Details:")
        print(f"  Serial number : {ssh_key.get('serialNumber', 'N/A')}")
        print(f"  Duration      : {ssh_key.get('duration', 'N/A')}")
        print(f"  Expires       : {ssh_key.get('expireTime', 'N/A')}")
        print(f"  Fingerprint   : {ssh_key.get('fingerprint', 'N/A')}")
        print()

        if not is_sign and "privateKey" in ssh_key:
            print("Private Key:")
            print(ssh_key["privateKey"])
            print()

        print("Certificate (Public Key):")
        print(ssh_key.get("publicKey", ""))

    print()
    print("Done.")


if __name__ == "__main__":
    main()
