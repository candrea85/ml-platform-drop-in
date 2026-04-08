# CLAUDE.md — ML Platform Drop-in

## What is this repo

Materials from the ML Platform bi-weekly drop-in sessions at CSCS. Each session has its own dated folder with presentation, documentation, and examples.

## Structure

```
<date>-<topic>/
├── README.md              # Session documentation
├── presentation/
│   └── slides.html        # Self-contained HTML presentation (base64 images, no external deps except Google Fonts)
├── examples/              # Scripts and code samples
└── reference/             # Reference materials (e.g. original scripts)
```

## Presentation conventions

- HTML slides, navigable with arrow keys
- Self-contained: logos embedded as base64, single file
- CSCS branding: red `#D61F26`, dark `#1A1A1A`, light `#F7F7F8`
- Font: Inter (Google Fonts)
- Media query `@media (min-width: 1800px)` scales fonts for 27" monitor screenshare
- All URLs must be clickable `<a>` with `target="_blank"`
- Background colors: grey `#F7F7F8` for regular cards, dark `#1A1A1A` only for legacy/reference boxes
- No em dashes in text
- Footer: "ML Platform drop-in · IAM tooling update" + slide number

## Audience

SwissAI community users of the ML Platform at CSCS. They use `portal.cscs.ch` for project/resource management. Do not reference "Waldur" directly (they know it as portal.cscs.ch).

## Naming conventions

- Session folders: `YYYY-MM-DD-<topic>`
- Example scripts with flow suffix: `*_user.py`, `*_service_account.py`, `*-user`, `*-service-account`
- Legacy CSCS CLI: `sshservice-cli` (official). ML community script: `cscs-cl` (custom)

## GitHub Pages

The repo is published via GitHub Pages. `index.html` at root redirects to the latest session's slides. Update the redirect when adding a new session.
