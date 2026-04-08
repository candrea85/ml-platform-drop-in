# SSH Key Generation — Migration Guide

> **Drop-in session — 2026-04-08**
>
> This guide explains how to generate SSH keys with the new CSCS SSH service,
> replacing the legacy `sshservice-cli` / `sshservice.cscs.ch` and community scripts like `cscs-cl`.

---

## Table of Contents

1. [Why the Change](#why-the-change)
2. [Two Flows: User Account vs Service Account](#two-flows-user-account-vs-service-account)
3. [Flow A: User Account (Browser Login)](#flow-a-user-account-browser-login)
4. [Flow B: Service Account (API Key)](#flow-b-service-account-api-key)
5. [API Reference](#api-reference)
6. [Examples](#examples)
7. [FAQ](#faq)

---

## Why the Change

The legacy tooling (the official `sshservice-cli` and community scripts like `cscs-cl`)
authenticates with **username + password + OTP** against a monolithic endpoint
(`sshservice.cscs.ch`). Every time your keys expired (every 24 hours), you had to
manually type your username, password, and a 6-digit OTP code to get new ones.
This makes automation impossible and daily interactive use tedious.

The new system provides **two flows** depending on your use case:

| | Old (sshservice-cli) | New: User Account | New: Service Account |
|---|---|---|---|
| **Who** | Any user | Standard users (humans) | Automated pipelines |
| **Auth** | Username + password + OTP | Browser OIDC login (one click) | API Key (set once, zero input) |
| **Key duration** | 24 hours | 1min, 1d | 1min only (ephemeral) |
| **Automation** | Not possible | Semi (needs browser) | Fully scriptable |
| **Daily workflow** | Run script → type 3 things → wait | Run script → click login → work | Run script → work |

> **"But 1-minute keys are very short!"** — The key is only needed for the initial
> SSH handshake. Once you are connected, the session stays alive indefinitely
> regardless of key expiry. You connect and work exactly as before.

---

## Two Flows: User Account vs Service Account

### Flow A: User Account (recommended for interactive use)

```
Script  ──▶  Opens browser (OIDC login)  ──▶  OIDC Access Token
                                                      │
                                                      ▼
Script  ──(Bearer Token)──▶  hpc-ssh / api-ssh-service
                                    │
                                    ▼
                              SSH key pair
```

Uses the same OIDC flow as the [cscs-key CLI](https://github.com/eth-cscs/cscs-key).
Your browser opens, you log in with your CSCS credentials, and the script receives
the token automatically via a local redirect. Supports durations of 1min and 1d.

### Flow B: Service Account (for automation / CI/CD)

```
Script  ──(API Key)──▶  hpc-user / api-service-account  ──▶  OIDC Access Token
                                                                      │
                                                                      ▼
Script  ──(Bearer Token)──▶  hpc-ssh / api-ssh-service
                                    │
                                    ▼
                              SSH key pair (ephemeral, 1min)
```

Fully non-interactive. No browser needed. Set the API Key once as an environment
variable and the script handles everything. Currently limited to 1min ephemeral keys.

---

## Flow A: User Account (Browser Login)

### Prerequisites

- A **standard CSCS user account** (the one you already have)
- A **browser** available on the machine running the script
- `curl`, `jq`, `python3` (for the bash script) or `requests` (for Python)

### How it works

1. The script starts a **local HTTP server** on `localhost:8765`
2. Opens your **browser** to the CSCS Keycloak login page
3. You log in with your **CSCS credentials** (same as the Webapp)
4. Keycloak redirects back to `localhost:8765` with an **authorization code**
5. The script exchanges the code for an **OIDC access token** (PKCE flow)
6. Uses the token to **generate or sign** an SSH key via `hpc-ssh`

### Quick start (curl)

```bash
# The browser-based flow requires a script — see the examples below.
# Here's what happens under the hood once you have a token:

# Generate a key pair (1-day duration)
curl -s -X POST \
  "https://authx-gateway.svc.cscs.ch/api-ssh-service/api/v1/ssh-keys" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"duration": "1d"}'

# Or sign your own public key
curl -s -X POST \
  "https://authx-gateway.svc.cscs.ch/api-ssh-service/api/v1/ssh-keys/sign" \
  -H "Authorization: Bearer YOUR_ACCESS_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"publicKey\": \"$(cat ~/.ssh/cscs-key.pub)\", \"duration\": \"1d\"}"
```

---

## Flow B: Service Account (API Key)

### Prerequisites

1. **A service account on Waldur** — Service accounts are not self-service yet.
   To get one:
   1. Open a **support ticket** at CSCS requesting service account access for your project.
   2. Specify: your **project name**, the **number of service accounts** needed
      (usually 1), and the **use case** (e.g. CI/CD pipeline, automated data transfer).
   3. CSCS reviews the request and, if approved, enables the **PI or Deputy PI**
      of the project to create service accounts on [portal.cscs.ch](https://portal.cscs.ch).
   4. The PI/Deputy PI creates the service account on Waldur and receives the **API Key**.

2. **Store the API Key securely** — Treat it like a password. Store it in a secrets
   manager, environment variable, or encrypted file. Never commit it to version control.

### How it works

1. Call the **hpc-user** token endpoint with your API Key
2. Receive an **OIDC access token**
3. Use the token to **generate or sign** an SSH key via `hpc-ssh`

### Quick start (curl)

```bash
# Step 1: Exchange API Key for token
TOKEN=$(curl -s -X POST \
  "https://authx-gateway.svc.cscs.ch/api-service-account/api/v1/auth/token" \
  -H "X-API-Key: YOUR_API_KEY" | jq -r '.access_token')

# Step 2: Generate an ephemeral key
curl -s -X POST \
  "https://authx-gateway.svc.cscs.ch/api-ssh-service/api/v1/ssh-keys" \
  -H "Authorization: Bearer $TOKEN" \
  -H "Content-Type: application/json" \
  -d '{}'
```

> **Current limitation**: Service accounts can only generate **ephemeral keys
> (duration: `1min`)**. The key expires after 60 seconds — generate it right before
> you need it.

### Endpoints

| Service | Purpose | Base URL |
|---|---|---|
| hpc-user (api-service-account) | Token exchange | `https://authx-gateway.svc.cscs.ch/api-service-account` |
| hpc-ssh (api-ssh-service) | SSH key operations | `https://authx-gateway.svc.cscs.ch/api-ssh-service` |

> **Note**: Replace with the correct production URLs for your environment.

---

## API Reference

### Generate SSH Key

| | |
|---|---|
| **Endpoint** | `POST /api/v1/ssh-keys` |
| **Service** | hpc-ssh (api-ssh-service) |
| **Authentication** | `Authorization: Bearer <token>` |
| **Success** | `201 Created` — returns key pair + certificate metadata |

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `duration` | string | No | `"1min"`, `"1d"` (default: `"1min"`). Service accounts: only `"1min"`. |
| `passphrase` | string | No | Encrypt the private key with a passphrase |
| `ipSubnets` | string[] | No | Restrict key usage to specific IP CIDR ranges |
| `forceCommand` | string | No | Restrict to a specific SSH command |

### Sign SSH Key

| | |
|---|---|
| **Endpoint** | `POST /api/v1/ssh-keys/sign` |
| **Service** | hpc-ssh (api-ssh-service) |
| **Authentication** | `Authorization: Bearer <token>` |
| **Success** | `201 Created` — returns signed certificate + metadata |

**Request body:**

| Field | Type | Required | Description |
|---|---|---|---|
| `publicKey` | string | **Yes** | The SSH public key to sign |
| `duration` | string | No | `"1min"`, `"1d"` (default: `"1min"`). Service accounts: only `"1min"`. |
| `ipSubnets` | string[] | No | Restrict key usage to specific IP CIDR ranges |
| `forceCommand` | string | No | Restrict to a specific SSH command |

### List SSH Keys

| | |
|---|---|
| **Endpoint** | `GET /api/v1/ssh-keys` |
| **Authentication** | `Authorization: Bearer <token>` |
| **Success** | `200 OK` |

### Revoke SSH Key

| | |
|---|---|
| **Endpoint** | `PUT /api/v1/ssh-keys/revoke` |
| **Authentication** | `Authorization: Bearer <token>` |
| **Request body** | `{"serialNumber": "...", "reason": "..."}` |

### Revoke All SSH Keys

| | |
|---|---|
| **Endpoint** | `PUT /api/v1/ssh-keys/revoke-all` |
| **Authentication** | `Authorization: Bearer <token>` |

---

## Duration and Rate Limits

| Duration | TTL | Max Active Keys | User Account | Service Account |
|---|---|---|---|---|
| `1min` | 60 seconds | Unlimited | Yes | Yes |
| `1d` | 24 hours | 5 per user | Yes | No |

Revoked keys do not count towards the active key limit.

---

## Examples

### User Account (browser login)

| File | Description |
|---|---|
| [`generate_ssh_key_user.py`](examples/generate_ssh_key_user.py) | Python script — browser OIDC login, supports all durations |
| [`cscs-cl-v2-user`](examples/cscs-cl-v2-user) | Bash script — drop-in replacement for the ML community's `cscs-cl`, with browser login |

```bash
# Python: generate a 1-day key and write to disk
python generate_ssh_key_user.py --duration 1d --output ~/.ssh/cscs-key --ssh-add

# Python: sign your own key
python generate_ssh_key_user.py --sign ~/.ssh/id_ed25519.pub --duration 1d

# Bash: just run it — logs in, generates key, connects to Clariden
./cscs-cl-v2-user
./cscs-cl-v2-user --secure   # adds passphrase to the key
```

### Service Account (API Key, fully automated)

| File | Description |
|---|---|
| [`generate_ssh_key_service_account.py`](examples/generate_ssh_key_service_account.py) | Python script — API Key auth, ephemeral keys only |
| [`cscs-cl-v2-service-account`](examples/cscs-cl-v2-service-account) | Bash script — API Key auth, generates + connects immediately |

```bash
# Set API Key once
export CSCS_SERVICE_ACCOUNT_API_KEY="your-api-key-here"

# Python: generate ephemeral key and write to disk
python generate_ssh_key_service_account.py --output ~/.ssh/cscs-key

# Python: sign your own key
python generate_ssh_key_service_account.py --sign ~/.ssh/cscs-key.pub

# Bash: generate key and connect to Clariden
./cscs-cl-v2-service-account
```

---

## FAQ

### Which flow should I use?

- **Interactive use** (you're a human at a terminal): use the **User Account** flow
  with browser login. You get longer key durations (up to 1d) and it works with your
  existing CSCS credentials.
- **Automation** (CI/CD, cron, pipelines): use the **Service Account** flow. It's
  fully non-interactive but limited to 1min ephemeral keys.

### Where do I get a service account?

Service accounts must be requested via a **CSCS support ticket**. Specify your
project, how many you need (usually 1), and your use case. Once approved, the
**PI or Deputy PI** creates the service account on
[portal.cscs.ch](https://portal.cscs.ch). The API Key is shown once — save it
immediately.

### How long does the API Key last?

Service account API Keys have a default TTL of 180 days. Rotate them via the
Waldur portal before they expire.

### What if my token or key expires mid-script?

Access tokens are short-lived (~5 minutes). For user accounts, keys can last
up to 24 hours. For service accounts, keys expire in 60 seconds. Always generate
a fresh key right before you need it.

### 60 seconds is very short — how do I work on the cluster?

The key is only needed for the **initial SSH handshake**. Once connected, your
session stays alive indefinitely. You can stay logged in and work for as long
as you need.

For non-interactive use (e.g. `scp`, `rsync`), generate the key and run the
command immediately in the same script.

### Can I restrict which IPs can use the generated key?

Yes, use the `ipSubnets` field. Example: `"ipSubnets": ["192.168.1.0/24"]`.

### Is my private key sent to the server when signing?

No. The `/sign` endpoint only receives your **public key**. Your private key
never leaves your machine. This is the recommended approach.

### What happens to the old tooling?

The legacy `sshservice.cscs.ch` endpoint and `sshservice-cli` will be deprecated.
The target retirement date is **April 20, 2026**, but this is not set in stone.
Depending on use cases and user feedback, the timeline may be extended. That said,
we encourage users to migrate to the new tooling as soon as possible.

If you use the ML community's [`cscs-cl`](https://github.com/swiss-ai/reasoning_getting-started/blob/main/cscs-cl)
script, see [`cscs-cl-v2-user`](examples/cscs-cl-v2-user)
(user account) or [`cscs-cl-v2-service-account`](examples/cscs-cl-v2-service-account) (service account) as drop-in replacements.

### The browser doesn't open / I'm on a headless server

The user account flow requires a browser. If you're on a headless server, use
either:
- The **service account** flow (fully non-interactive)
- The **cscs-key CLI** (`cscs-key sign`) which can handle remote auth flows
