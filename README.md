<p align="center">
  <img src="assets/branding/opl-persona-logo.png" alt="OPL Persona logo" width="136" />
</p>

<p align="center">
  <a href="./README.md"><strong>English</strong></a> | <a href="./README.zh-CN.md">中文</a>
</p>

# OPL Persona

**An evidence-backed digital counterpart for a PI's ongoing work.**

OPL Persona helps one person keep mail, knowledge, professional context, and
public-facing work connected without taking ownership away from the systems
where that information belongs. It turns evidence from OPL Relay, the user's
selected knowledge sources, and a lab website into reviewable proposals.
Obsidian and ordinary Markdown directories can remain the canonical home of
personal knowledge.

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

Four callable working modes cover academic mail, technical memo, academic
website and research writing. People, memories and customized working modes
are derived context bound to accepted source versions. Framework checks their
sources before memory approval and every context assembly; expired, changed,
missing or revoked sources are excluded with a diagnostic. Management includes
candidates by default and can show forgotten entries, while invalid derived
content is withheld until its sources are repaired. Relay mail memory is read through
its public Package ABI, never its database. Triage, capture and note proposals
persist across CLI runs; inspect/approve/reject bind their exact digest.
Obsidian application needs a separate, exact resource grant grounded in user authorization and
returns a persisted authority readback. Review never authorizes send/publish.

`context list/select/update`, `people list/update`, `memory list/update/review`,
and `proposal list/inspect/approve/reject/authorize-obsidian/apply-obsidian`
share the Package JSON contracts (`--input <file-or->`). Concurrent CLI writers
share a cross-platform lock and atomic saves under `data/persona`. Studio views
mount in the existing `settings.section` slot; read models supply localized
modes, action forms and digest-bound row inputs.

## The Profile Workspace

Each digital counterpart has one user-owned **Profile Workspace**. It holds
private source bindings, derived context, policies, proposal state, and
module-maintained data. Personal source documents stay where the user maintains
them; local notes are optional. A typical workspace is:

```text
~/OPL/profiles/<profile>/
├── profile/            # References, or explicitly selected local source notes
├── policies/           # Optional local rules/templates; register before use
├── context/            # Optional local project sources
├── templates/          # Reusable personal templates
├── exports/            # Explicit user-facing outputs
└── data/
    ├── relay/          # Mail evidence, drafts, memory, and sync state
    └── persona/        # Role refs, derived context, inbox, proposals, and receipts
```

Select the workspace with the single `OPL_PROFILE_WORKSPACE` environment
variable. Without it, Persona uses `~/OPL/profiles/<user>`. The source checkout,
Codex Plugin cache, and any OPL Package installation contain code and contracts
only; they are never a home for private mail, vault contents, credentials, or
approvals.

Mail policy and context are selected by knowledge IDs in
`data/persona/knowledge-inputs.json`. Framework resolves accepted sources from
the registry selected by `shared/memory/knowledge-bindings.json` through its
`registry_ref` (for example, the Profile's `data/knowledge-sources.json`); local policy templates do not
automatically become evidence. Existing documents can be registered in place.
See [Mail policy](docs/mail-policy.md) for the role mapping and read contract.

## Start Locally

Clone the repository, install the development CLI, and initialize a Profile
Workspace:

```bash
git clone git@github.com:gaofeng21cn/opl-persona.git
cd opl-persona
make install-local

export OPL_PROFILE_WORKSPACE="$HOME/OPL/profiles/<profile>"
opl-persona --json setup init
opl-persona --json setup status
```

`setup init` is idempotent and creates missing control directories and handling
policies without overwriting user content. `setup status` reports runtime
configuration, not completeness of personal facts. It requires neither an
external knowledge library nor a duplicate identity note.

If this workspace is the chosen home for personal source notes, create the
optional templates:

```bash
opl-persona --json setup init --local-knowledge
```

For an existing note directory, record a scoped reference. Use `obsidian` for an
Obsidian vault or `markdown` for an ordinary directory:

```bash
opl-persona --json binding set \
  --id my-knowledge --provider obsidian --path "/path/to/Obsidian"
opl-persona --json binding check --id my-knowledge
```

Persona does not read the vault during binding setup. Configure mail separately
with OPL Relay using the same Profile Workspace.

These Resource Bindings serve note adapters. Accepted knowledge identities,
versions and read grants use the Framework's shared source mechanism; a Persona
note binding does not grant general knowledge access. `people update`,
`memory update` and `context update` require `source_versions`, an object mapping
each accepted `knowledge_id` to its exact `sha256:...` revision. A new independent
preference is first accepted in its canonical source, then referenced here.
Existing v1 workspace records can be preserved and moved to source review with
`opl-persona --json workspace-migrate`; previous approvals do not establish source
currentness. The family-wide authority is the
[OPL knowledge source and memory policy](https://github.com/gaofeng21cn/one-person-lab/blob/main/docs/policies/knowledge-source-and-memory-policy.md).

For the complete proposal contract and owner boundaries, see
[Persona Architecture](./docs/architecture.md). Cross-repository target design
is in [Architecture Guidance](./docs/architecture-guidance.md).

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

From GitHub:

```bash
codex plugin marketplace add https://github.com/gaofeng21cn/opl-persona.git --ref main --json
codex plugin list --marketplace opl-persona --available --json
codex plugin add opl-persona@opl-persona --json
```

After installation, start a new Codex task so it loads the installed Plugin
snapshot. For normal work, ask Codex in natural language and let the Plugin
route to the declared Package actions. It produces proposals and uses existing
authorization when that authorization covers the exact target and change;
missing or expanded authority requires user review.

To refresh a Git marketplace snapshot, then reinstall the Plugin snapshot:

```bash
codex plugin marketplace upgrade opl-persona --json
codex plugin add opl-persona@opl-persona --json
```

## Distribution

There are two distinct distribution paths:

| Path | Status today | What it means |
| --- | --- | --- |
| Codex Plugin | Native Codex carrier; current state comes from `codex plugin list --json` | Installs and exposes the Persona Skill carrier without making the checkout or Plugin cache a data authority. |
| OPL Package publication | Persona owner descriptor plus immutable GHCR payloads | Publishes Package identity and bytes independently; `latest-stable` is a moving owner channel, not installed-state proof. |

The Persona repository owns its descriptor, capability declarations, source
provenance, and Package publication. OPL Base may download, verify, and hand off
selected OCI bytes; the configured native carrier owns physical install,
update, repair, removal, and its own readback. OPL Framework discovers installed
descriptors, delegates carrier actions, and aggregates presence and callability
for OPL App. Persona does not implement a second updater. Its stable owner
channel is:

```text
ghcr.io/gaofeng21cn/one-person-lab-packages/opl-persona:latest-stable
```

GitHub Releases are not part of Persona distribution. The Codex Git path and
the OPL Package path share source provenance but have separate lifecycle
authorities. Publication must be read from the public immutable GHCR digest;
installed/current state must be read separately from the configured native
carrier. Neither may be inferred from this README, a source tag, or Framework
projection alone.

See [Distribution](./docs/distribution.md) for the exact authority and
verification boundaries.

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

OPL Persona is available under the [Apache License 2.0](./LICENSE).
