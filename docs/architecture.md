# OPL Persona Architecture

Owner: `opl-persona`

Purpose: `persona_current_implementation`

State: `active`

Machine boundary: This document describes the current Persona implementation.
The Package descriptor, runtime source, and tests remain machine authority.
[Architecture Guidance](architecture-guidance.md) owns the cross-repository
target design; its form and portal surfaces are not current exports merely
because they are documented.

## Owner split

Persona is a judgment and proposal layer. It does not become a second mail
store, knowledge vault, or website CMS.

| Surface | Authority |
| --- | --- |
| OPL Relay | mail identities, raw mail evidence, memory evidence, drafts, send receipts |
| Obsidian | private notes, memo content, and all user-maintained personal profile values |
| `gflab_web` | public publication/news content and deployment |
| OPL Persona | shared PI context, provenance, proposal shape, approval state |

## Current exported surfaces

The Package descriptor exports one Skill, `opl-persona`, and these Core module
identities:

```text
personal.context.v1
personal.memory.v1
personal.inbox.v1
knowledge.obsidian.v1
communications.mail.v1
website.publication.v1
```

The CLI implements proposal builders for publication, memo, mail triage, Inbox
capture, and Obsidian notes. Its current proposal routes are:

```text
publication input -> knowledge.publication + gflab_web.content.publication
Obsidian memo -> gflab_web.content.post + opl-relay.draft.context
mail evidence -> communications.mail.v1#triage + personal.inbox.v1
Inbox input -> personal.inbox.v1
knowledge input -> knowledge.obsidian.note.v1
```

The App contribution ABI exposes three data refs and five action refs. Only
`personal.inbox.v1#recent` has a configured read-model store. Context reads
return `input_required`; proposal inspect/approve return
`owner_handler_required`. The executable proposal actions are limited to:

```text
communications.mail.v1#triage.propose
personal.inbox.v1#capture.propose
knowledge.obsidian.v1#note.propose
```

## Current proposal contract

The only cross-system write primitive is a reviewable proposal:

```text
source evidence -> opl-persona-proposal.v1 -> user review -> owner adapter
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

## Current Resource Binding

The private binding store is
`<profile>/data/persona/resource-bindings.json`. It holds opaque refs, scopes,
policy metadata, and health metadata; it never holds credentials or authority
content. The current CLI can set and check only an Obsidian directory binding,
with `knowledge.obsidian.v1` or `knowledge.documents.v1` as the capability. The
health check proves directory reachability only.

Persona therefore has no current personal-profile field registry, form model,
form action, external-portal provider, portal adapter, or submission receipt.
Those are target designs in
[Personal Profile and Form Fill](personal-profile-form-fill.md),
[External Professional Work](external-professional-work.md), and
[Composable Capability and Integration Model](integration-capability-composition.md).
They do not become callable through a generic Resource Binding record.

## Runtime data

`OPL_PROFILE_WORKSPACE` selects the user's single Profile Workspace. Persona
stores its machine-maintained state under `<workspace>/data/persona`; Relay
uses the sibling `<workspace>/data/relay`. When unset, Persona uses
`~/OPL/profiles/<user>` and its `data/persona` child. The
repository, installed plugin, and Package are never data authorities.
