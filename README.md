<p align="center">
  <img src="assets/branding/opl-persona-logo.png" alt="OPL Persona logo" width="136" />
</p>

<p align="center">
  <a href="./README.md"><strong>English</strong></a> | <a href="./README.zh-CN.md">中文</a>
</p>

# OPL Persona

**A private, evidence-backed digital counterpart for a PI's ongoing work.**

OPL Persona helps one person keep mail, knowledge, professional context, and
public-facing work connected without taking ownership away from the systems
where that information belongs. It turns evidence from OPL Relay, an Obsidian
vault, and a lab website into explicit proposals that can be reviewed before
anything is changed.

It is designed for work that continues across conversations: keeping a
relationship-aware mail response grounded in prior evidence, turning a new
publication into a knowledge and website update, or developing a technical
memo from the context already available to the PI.

## What Persona Does

- Brings together evidence and context from mail, personal knowledge, and
  website work without copying their source data into a new database.
- Maintains a private cross-domain Inbox for information that needs to be
  assessed, organized, or turned into an action.
- Produces reviewable proposals for mail triage, Obsidian notes, and website
  updates, with source references and policy context.
- Keeps external writes under the authority of their owner: Relay handles mail
  facts, drafts, Apple Mail review, sending, and receipts; Obsidian owns notes;
  and the website repository owns publication and deployment.

Persona is a judgment and coordination layer. It is not a replacement mail
client, a second Obsidian vault, or a website CMS.

## The Profile Workspace

Each digital counterpart has one user-owned **Profile Workspace**. It holds
private profile context, preferences, policies, proposal state, and
module-maintained data. A typical workspace is:

```text
~/OPL/profiles/<profile>/
├── profile/            # Who this person is and durable profile references
├── policies/           # Personal handling rules
├── context/            # Ongoing work context
├── templates/          # Reusable personal templates
├── exports/            # Explicit user-facing outputs
└── data/
    ├── relay/          # Mail evidence, drafts, memory, and sync state
    └── persona/        # Inbox, proposals, approvals, and receipts
```

Select the workspace with the single `OPL_PROFILE_WORKSPACE` environment
variable. Without it, Persona uses `~/OPL/profiles/<user>`. The source checkout,
Codex Plugin cache, and any OPL Package installation contain code and contracts
only; they are never a home for private mail, vault contents, credentials, or
approvals.

## Start Locally

Clone the repository, install the development CLI, and initialize a Profile
Workspace:

```bash
git clone git@github.com:gaofeng21cn/opl-persona.git
cd opl-persona
make install-local

export OPL_PROFILE_WORKSPACE="$HOME/OPL/profiles/<profile>"
opl-persona workspace-init
opl-persona doctor
```

`workspace-init` creates the safe directory skeleton and marker. It does not
import mail, copy an Obsidian vault, or connect an account. Configure private
resource bindings only inside the selected Profile Workspace.

For the complete proposal contract and owner boundaries, see
[Architecture Guidance](./docs/architecture-guidance.md).

## Use With Codex

This repository ships a Codex Plugin carrier. Codex can add the marketplace
from a local checkout or from this Git repository. The marketplace identifier
is `opl-persona` in both cases.

From a local checkout:

```bash
codex plugin marketplace add "$(pwd -P)" --json
codex plugin list --marketplace opl-persona --available --json
codex plugin add opl-persona@opl-persona --json
```

From Git, using credentials that can read this repository:

```bash
codex plugin marketplace add git@github.com:gaofeng21cn/opl-persona.git --ref main --json
codex plugin list --marketplace opl-persona --available --json
codex plugin add opl-persona@opl-persona --json
```

After installation, start a new Codex task so it loads the installed Plugin
snapshot. For normal work, ask Codex in natural language and let the Plugin
route to the declared Package actions. It will produce proposals first; it
does not silently edit mail, an Obsidian vault, or a website.

To refresh a Git marketplace snapshot, then reinstall the Plugin snapshot:

```bash
codex plugin marketplace upgrade opl-persona --json
codex plugin add opl-persona@opl-persona --json
```

## Distribution Status

There are two distinct distribution paths:

| Path | Status today | What it means |
| --- | --- | --- |
| Codex Plugin | Available from a local checkout or a Git marketplace snapshot | Lets Codex install the Persona Skill carrier. |
| OPL managed Package | Planned | Will let OPL App discover, install, update, repair, and remove Persona through the shared Package lifecycle. |

The Git repository is a source and a Codex marketplace input. It is **not yet**
an OPL managed Package channel, and OPL App cannot honestly claim automatic
remote installation or update for Persona today. The target channel will be
owned by OPL Framework through its repository index, immutable Package payload,
manifest, and digest readback rather than by a Persona-specific updater.

See [Distribution](./docs/distribution.md) for the current boundary and the
release work still required.

## Development Checks

```bash
python3 -m pytest -q
actionlint .github/workflows/ci.yml
```

Before release, maintainers also run the official `validate_plugin.py` supplied
with the active Codex Plugin Creator. Its installation path is intentionally
not hard-coded in this repository. GitHub Actions runs portable structural
checks in addition to the test suite.

## License

OPL Persona is available under the [MIT License](./LICENSE).
