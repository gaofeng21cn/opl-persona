# OPL Persona

OPL Persona is the cross-domain personal context layer for OPL. It turns
evidence-backed inputs from mail, Obsidian, and the lab website into explicit,
reviewable output proposals.

The cross-repository design authority is
[`docs/architecture-guidance.md`](docs/architecture-guidance.md). Read it
before changing a domain boundary, adding a new adapter, or deciding whether a
feature belongs in Persona, Relay, OPL App, or an authority-owned repository.

Persona does not own mail, Obsidian, or website data. Those systems remain the
authorities for their own content. Persona stores only contracts, reasoning
inputs, provenance, and proposal state under the user's Profile Workspace:
`<profile>/data/persona`. Relay uses the sibling `<profile>/data/relay`; the
installed Plugin and Package never contain user data.

## v1 workflow

```text
publication input -> knowledge ingestion proposal + website update proposal
Obsidian memo      -> website article proposal + Relay mail draft context
```

Every external write is a proposal until the user approves it. The package,
plugin, and source checkout never contain private data.

Private mail judgment rules live as Markdown under the configured Profile
Workspace (`<profile>/policies/`, selected by `OPL_PROFILE_WORKSPACE`). Persona loads those rules and
records a content digest in each `mail.triage` proposal; OPL Relay remains the
mail fact, draft, send, and receipt authority. See
[`docs/mail-policy.md`](docs/mail-policy.md) for the boundary and routing
contract.

## Local installation

```bash
make install-local
OPL_PROFILE_WORKSPACE=~/OPL/profiles/<user> opl-persona doctor
```

Install or update the Codex Plugin carrier through this repository's local
marketplace; do not maintain plugin cache copies by hand. Obsidian bindings
live in `<profile>/data/persona/resource-bindings.json`. CLI callers select a
binding id and never pass a vault absolute path or a module-specific
environment variable.
