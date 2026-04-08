# Speaker Notes -- IAM Tooling Update (2026-04-08)

## Slide 1: Title -- IAM Tooling Update for ML Platform Users

- Welcome everyone, thank you for joining this drop-in session.
- I am Andrea Ceriani, Software Engineer in the IAM team and Service Manager for the ML Platform. With me today are Francesco Pagnamenta and Davide Mazzoleni, also from the IAM team.
- Today we will talk about the new IAM tooling for SSH workflows: the new User Account Webapp, the new CLI, and the different account types.
- We will do a live demo of the Webapp and the CLI, and we will leave time for questions and feedback at the end.
- The main message is simple: use the new Webapp for web workflows, the new CLI for command-line workflows, and the updated documentation on docs.cscs.ch as your main reference.

---

## Slide 2: Context -- IAM modernization and the SSH Service

- The adoption of portal.cscs.ch required a modernization of the IAM services and the tooling around them.
- The SSH Service is a core service -- it is how users access the centre. Over the last months, the IAM team completed a full refactoring of the backend API, the web frontend, and the CLI.
- The new version has been in production for a few weeks, currently for internal use. Today we are introducing it to the ML Platform community.
- About the legacy service: the old SSH Service (sshservice.cscs.ch) and sshservice-cli are still active and working. The target retirement date is April 20, but this is not set in stone. Depending on your feedback and use cases, we can extend the timeline. That said, we encourage everyone to migrate to the new tooling as soon as possible.
- Your feedback matters. This session is also an opportunity for us to collect feedback and prioritize improvements based on your real-world needs.
- The core concept is unchanged: users access CSCS with CSCS-signed SSH keys. What is new is the tooling. The recommended flow is now: generate your key locally, then sign it. Your private key never leaves your machine.

---

## Slide 3: What this means for users

- We are modernizing the IAM tooling to simplify user workflows and improve service quality.
- In practice, the changes are:
  - Clearer entry points: one web entry point for account and SSH workflows.
  - Updated SSH workflows: you can generate keys as before, or sign a local key with the new flow.
  - Better automation: the new CLI and service accounts support structured automation for pipelines and CI/CD.
  - Better supportability: more auditable services mean smoother operations and troubleshooting.
- For users, the main practical change is simple: use the new Webapp and the new CLI for SSH workflows, and rely on the updated documentation as the main reference.

---

## Slide 4: What should users use now?

- Two main entry points:
  - **User Account Webapp** (user-account.cscs.ch): the recommended web entry point for SSH workflows. You can sign an existing local key (recommended), generate a new key pair server-side, or list and revoke your SSH keys.
  - **New CLI** (cscs-key): for shell-based workflows. The main commands are `cscs-key sign`, `cscs-key list`, and `cscs-key revoke`. For custom integrations, you can use the API directly.
- The recommended flow is: generate your key locally (`ssh-keygen`), then sign it via the Webapp or CLI. Your private key never leaves your machine.
- Note on cscs-key binary signing: the CLI distributes pre-built binaries for Linux, macOS, and Windows. Some users may see security warnings because the binaries are not yet signed. Signed binaries will be available soon. Please let us know if you need support.

---

## Slide 5: Which account should I use?

- Three types of accounts:
  - **Standard User**: your personal CSCS account, for human access to Alps. Can span multiple projects.
  - **Service Account**: for automation and CI/CD. Project-scoped, non-human, ephemeral keys only (1 minute). Requires a request to IAM via support ticket -- specify your project name, number of accounts needed, and use case. Once approved, the PI or Deputy PI can create them on portal.cscs.ch.
  - **Temporary Account**: for short-lived event access (courses, trainings, workshops, hackathons). Simpler onboarding, expires automatically.
- Rule of thumb: logging in as yourself -- Standard User. Pipelines or unattended jobs -- Service Account. Course or training -- Temporary Account.

---

## Slide 6: Live Demo

- We will do a quick walkthrough of the two main entry points.
- **Webapp demo**: open the User Account Webapp, navigate to SSH key management, walk through the updated flow (generate or sign), show key listing and revocation.
- **CLI demo**: introduce the new CLI and installation, show the basic user flow (sign, list, revoke), highlight scripting and automation use cases, point to the repo and documentation.
- The legacy service is still active while the new tooling is being introduced.

---

## Slide 7: Q&A -- Questions, feedback, and next steps

- Thank you for your time.
- We welcome questions and feedback:
  - Questions on the new Webapp, the new CLI, or SSH workflows?
  - Unsure which account type fits your use case?
  - Feedback on documentation, usability, or missing guidance?
- About the retirement date: the target is April 20, but it is not set in stone. Depending on your use cases and feedback, we can extend the timeline. The goal is to migrate as soon as practical, but we want to make sure the transition is smooth for everyone.
- Useful references are on screen: the Webapp, the CLI repo, the SSH documentation, the drop-in materials repo, and the support email.
