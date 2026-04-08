#!/usr/bin/env python3
"""
Generate or sign SSH keys using the CSCS HPC SSH service with a service account.

Note: Service accounts are currently limited to ephemeral keys (1min duration).
The key expires 60 seconds after generation — use it immediately.

Usage:
    # Generate a new key pair (server-side)
    python generate_ssh_key.py --api-key YOUR_API_KEY

    # Sign your own public key (private key stays local)
    python generate_ssh_key.py --api-key YOUR_API_KEY --sign ~/.ssh/cscs-key.pub

    # Use environment variable for the API key
    export CSCS_SERVICE_ACCOUNT_API_KEY="YOUR_API_KEY"
    python generate_ssh_key.py

    # Restrict to specific IPs
    python generate_ssh_key.py --api-key YOUR_API_KEY --ip-subnets 192.168.1.0/24 10.0.0.0/8

    # Write keys to disk
    python generate_ssh_key.py --api-key YOUR_API_KEY --output ~/.ssh/cscs-key

    # Generate key and run an SSH command in one shot
    python generate_ssh_key.py --api-key YOUR_API_KEY --output ~/.ssh/cscs-key \
        --run "ssh -i ~/.ssh/cscs-key clariden.cscs.ch hostname"

Requirements:
    pip install requests  (or: uv pip install requests)
"""

from __future__ import annotations

import argparse
import json
import os
import stat
import subprocess
import sys
from pathlib import Path

try:
    import requests
except ImportError:
    print("Error: 'requests' package is required. Install it with:")
    print("  pip install requests")
    sys.exit(1)

# ---------------------------------------------------------------------------
# Configuration — adjust these URLs to match your environment
# ---------------------------------------------------------------------------
DEFAULT_HPC_USER_BASE_URL = os.environ.get(
    "HPC_USER_BASE_URL",
    "https://authx-gateway.tds.cscs.ch/api-service-account",
)
DEFAULT_HPC_SSH_BASE_URL = os.environ.get(
    "HPC_SSH_BASE_URL",
    "https://authx-gateway.tds.cscs.ch/api-ssh-service",
)

TOKEN_ENDPOINT = "/api/v1/auth/token"
GENERATE_ENDPOINT = "/api/v1/ssh-keys"
SIGN_ENDPOINT = "/api/v1/ssh-keys/sign"

# Service accounts are currently limited to 1min ephemeral keys only.
VALID_DURATIONS = ("1min",)
DEFAULT_DURATION = "1min"


# ---------------------------------------------------------------------------
# Step 1: Exchange API Key for OIDC Access Token
# ---------------------------------------------------------------------------
def get_access_token(api_key: str, base_url: str) -> str:
    """Exchange a service account API Key for an OIDC access token."""
    url = f"{base_url}{TOKEN_ENDPOINT}"

    print(f"  Requesting access token from {url} ...")

    response = requests.post(
        url,
        headers={"X-API-Key": api_key},
        timeout=30,
    )

    if response.status_code == 401:
        print("Error: Invalid API Key. Check your service account credentials.")
        sys.exit(1)
    if response.status_code == 403:
        print("Error: Service account is disabled or inactive.")
        sys.exit(1)

    response.raise_for_status()

    data = response.json()
    access_token = data.get("access_token")
    if not access_token:
        print("Error: No access_token in response.")
        print(f"Response: {json.dumps(data, indent=2)}")
        sys.exit(1)

    expires_in = data.get("expires_in", "unknown")
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
        print("Error: Access token is invalid or expired. Request a new one.")
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
        print("Error: Access token is invalid or expired. Request a new one.")
        sys.exit(1)

    response.raise_for_status()
    return response.json()


# ---------------------------------------------------------------------------
# Write keys to disk
# ---------------------------------------------------------------------------
def write_keys(output_path: Path, ssh_key: dict, is_sign: bool) -> None:
    """Write SSH key files to disk with correct permissions."""
    cert_path = output_path.with_name(f"{output_path.name}-cert.pub")

    # Write the signed certificate
    public_key = ssh_key.get("publicKey", "")
    cert_path.write_text(public_key + "\n")
    os.chmod(cert_path, stat.S_IRUSR | stat.S_IWUSR | stat.S_IRGRP | stat.S_IROTH)  # 644
    print(f"  Certificate written to {cert_path}")

    # Write the private key (only available with generate, not sign)
    if not is_sign:
        private_key = ssh_key.get("privateKey", "")
        if private_key:
            output_path.write_text(private_key + "\n")
            os.chmod(output_path, stat.S_IRUSR | stat.S_IWUSR)  # 600
            print(f"  Private key written to {output_path}")

    # Print metadata
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
        subprocess.run(
            ["ssh-add", "-t", ttl, str(key_path)],
            check=True,
        )
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
        description="Generate or sign SSH keys via the CSCS HPC SSH service.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --api-key SECRET --duration 1d
  %(prog)s --api-key SECRET --duration 1d --sign ~/.ssh/id_ed25519.pub
  %(prog)s --duration 1d --output ~/.ssh/cscs-key
  CSCS_SERVICE_ACCOUNT_API_KEY=SECRET %(prog)s --duration 1d
        """,
    )
    parser.add_argument(
        "--api-key",
        default=os.environ.get("CSCS_SERVICE_ACCOUNT_API_KEY"),
        help="Service account API Key (or set CSCS_SERVICE_ACCOUNT_API_KEY env var)",
    )
    parser.add_argument(
        "--duration",
        choices=VALID_DURATIONS,
        default=DEFAULT_DURATION,
        help="Key duration (default: 1min). Service accounts only support 1min.",
    )
    parser.add_argument(
        "--sign",
        metavar="PUBLIC_KEY_FILE",
        help="Path to an existing public key to sign (instead of generating a new pair)",
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
        help="Restrict key to specific IP subnets (e.g. 192.168.1.0/24)",
    )
    parser.add_argument(
        "--force-command",
        metavar="CMD",
        help="Restrict the key to a specific SSH command",
    )
    parser.add_argument(
        "--hpc-user-url",
        default=DEFAULT_HPC_USER_BASE_URL,
        help=f"hpc-user base URL (default: {DEFAULT_HPC_USER_BASE_URL})",
    )
    parser.add_argument(
        "--hpc-ssh-url",
        default=DEFAULT_HPC_SSH_BASE_URL,
        help=f"hpc-ssh base URL (default: {DEFAULT_HPC_SSH_BASE_URL})",
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Output raw JSON response instead of writing files",
    )
    parser.add_argument(
        "--run",
        metavar="CMD",
        help="Shell command to run immediately after key generation (key expires in 60s)",
    )

    args = parser.parse_args()

    if not args.api_key:
        parser.error(
            "API Key is required. Use --api-key or set CSCS_SERVICE_ACCOUNT_API_KEY."
        )

    return args


def main() -> None:
    args = parse_args()

    print("CSCS SSH Key Generator (Service Account)")
    print("=" * 42)
    print()

    # Step 1: Get access token
    print("[1/2] Authenticating with service account ...")
    access_token = get_access_token(args.api_key, args.hpc_user_url)
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
            base_url=args.hpc_ssh_url,
            public_key=public_key,
            duration=args.duration,
            ip_subnets=args.ip_subnets,
            force_command=args.force_command,
        )
    else:
        print("[2/2] Generating SSH key pair ...")
        result = generate_ssh_key(
            access_token=access_token,
            base_url=args.hpc_ssh_url,
            duration=args.duration,
            ip_subnets=args.ip_subnets,
            force_command=args.force_command,
        )

    print()

    # Output
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
        # Print to stdout
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

    # Run a command immediately if requested (key expires in 60s)
    if args.run:
        print()
        print(f"  Running: {args.run}")
        result_code = subprocess.run(args.run, shell=True).returncode
        sys.exit(result_code)

    print()
    print("Done.")


if __name__ == "__main__":
    main()
