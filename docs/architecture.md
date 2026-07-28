# OPL Persona Architecture

The cross-repository design authority is
[Architecture Guidance](architecture-guidance.md). This file keeps the
Persona-specific owner split and v1 contract close to the implementation.

## Owner split

Persona is a judgment and proposal layer. It does not become a second mail
store, knowledge vault, or website CMS.

| Surface | Authority |
| --- | --- |
| OPL Relay | mail identities, raw mail evidence, memory evidence, drafts, send receipts |
| Obsidian | private notes, memo content, and all user-maintained personal profile values |
| `gflab_web` | public publication/news content and deployment |
| OPL Persona | shared PI context, provenance, proposal shape, approval state |

## v1 contract

The only cross-system write primitive is a reviewable proposal:

```text
publication -> knowledge.ingest + website.publication
Obsidian memo -> website.article + mail.draft_context
mail evidence -> personal.inbox.v1 capture + mail.triage
knowledge input -> knowledge.obsidian.note.v1 create/update proposal
personal profile -> personal.form.* draft/fill proposal
```

Each proposal contains a stable id, an explicit target, payload, source
references, and `approval.external_write_allowed=false`. An adapter can execute
only an exact user-approved proposal. A proposal is not a published website
change, sent email, or written vault note.

## Inbox and Obsidian proposal contracts

`mail.triage` is a policy-bound interpretation of one validated Relay
`opl-relay-mail-triage-evidence.v2` facts envelope with a canonical
`email-store://` source reference. Persona loads the user's private Markdown
rules from `<profile>/policies/` and hashes the selected file bytes,
not merely a list of policy refs. It records a classification, priority,
rationale, uncertainty, recommended action, policy references, and a content
`policy_digest`. Recipient evidence (`to`, `cc`, `bcc`) comes only from Relay.
Persona resolves the user's own addresses, actual first author, team-member
match, forwarding target, follow-up owner, and notification suggestion from
the selected Profile's private Markdown context and records a separate
`context_digest`. A Relay refs-set digest is retained only as
`relay_policy_digest` provenance and never becomes Persona's content digest.
The proposal also emits a generic `personal.inbox.v1` capture for Persona's
private staging provider. The Inbox stores only source refs, a bounded summary,
state, and owner routes; it does not copy the mail body. An App may project that
staging without becoming a second mailbox. Missing mail, policy, or identity
provenance fails closed.

`knowledge.obsidian.note.v1` is a proposal for exactly one relative Markdown
target path. It carries frontmatter, body, links, tags, evidence references,
and a target precondition: `expected_digest` is `absent` for creation or the
current SHA-256 digest for update. Persona has no apply operation. The note
adapter must check that precondition after the user approves the exact proposal
and before any vault write.

## Personal profile and external professional work

Personal profile values, including identity, employment, contact, payment,
tax, and document fields, are maintained in the user's Obsidian vault for
convenient reuse. Persona keeps only field references, provenance, currentness,
purpose, and approval state; it does not create a second profile database or
copy those values into Git, plugin caches, chat history, or App state.
The vault path is supplied only by a Profile Workspace Resource Binding; Persona
does not carry a default vault path or environment-variable override.
The private binding store is
`<profile>/data/persona/resource-bindings.json`. Callers select a binding by
opaque id; only the Obsidian owner adapter resolves its `file://` resource ref
at the point of use.

The detailed contracts are:

- [Composable Capability and Integration Model](integration-capability-composition.md)
  — Package、Capability、Provider、Binding 与 Persona Recipe 的组合边界。
- [Personal Profile and Form Fill](personal-profile-form-fill.md) — the
  `personal_profile` and `form_fill` Core boundary and form adapters.
- [External Professional Work](external-professional-work.md) — third-party
  professional portals, task scope, and per-action approval.

Portal login credentials and authenticated browser sessions remain separate
from personal profile values and follow the portal access policy.

Knowledge, mail, website, form, and portal integrations are optional capability
providers rather than hard-coded Persona subsystems. The PI recipe recommends a
knowledge binding and can select mail, website, form, or portal bindings only
when the user configures them.

## Runtime data

`OPL_PROFILE_WORKSPACE` selects the user's single Profile Workspace. Persona
stores its machine-maintained state under `<workspace>/data/persona`; Relay
uses the sibling `<workspace>/data/relay`. When unset, Persona uses
`~/OPL/profiles/<user>` and its `data/persona` child. The
repository, installed plugin, and Package are never data authorities.
