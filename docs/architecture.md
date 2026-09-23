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

These are package-scoped capability surfaces, not ownership claims over mail,
Obsidian content, or the website. An App action is addressed by both
`package_id` and its action ref. Relay retains mail authority even when Persona
exposes a mail triage proposal action.

The CLI implements proposal builders for publication, memo, mail triage, Inbox
capture, and Obsidian notes. Its current proposal routes are:

```text
publication input -> knowledge.publication + gflab_web.content.publication
Obsidian memo -> gflab_web.content.post + opl-relay.draft.context
mail evidence -> communications.mail.v1#triage + personal.inbox.v1
Inbox input -> personal.inbox.v1
knowledge input -> knowledge.obsidian.note.v1
```

The App contribution ABI exposes three data refs and five action refs. The
Persona-owned read-model store serves both `personal.context.v1#today` and
`personal.inbox.v1#recent` as refs-only projections: `today` includes active
(`staged` or `routed`) Inbox entries, while `recent` includes all entries. The
projection contains bounded summaries and opaque source refs, never source
content. `personal.context.v1#proposals` remains `input_required`; proposal
inspect/approve return `owner_handler_required`. The executable proposal
actions are limited to:

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

`mail.triage` consumes one validated Relay facts envelope, an agent assessment
bound to the same email reference, and Persona's private policy/context
snapshots. It validates the decision and produces a reviewable proposal and a refs-only
Inbox capture; missing evidence fails closed. Policy loading, content digests
and recipient interpretation belong to [Mail Policy](mail-policy.md).
Persona never treats the Relay refs-set digest as its own policy-content
digest or turns a triage proposal into a mailbox write.

`inbox.py` stores `opl-persona-inbox.v1` at `data/persona/inbox/items.json`.
Its item states are `staged`, `routed`, `consumed`, and `discarded`; route refs
are opaque references. `consumed` is a local recorded state, not independently
verified external delivery. A caller must obtain the target owner's receipt
before using it to report successful delivery.

`knowledge.obsidian.note.v1` is a proposal for exactly one relative Markdown
target path. It carries frontmatter, body, links, tags, evidence references,
and a target precondition: `expected_digest` is `absent` for creation or the
current SHA-256 digest for update. The CLI and App proposal actions do not apply
notes. The separate owner adapter in `obsidian_apply.py` implements
`apply_approved_obsidian_note`: it requires an exact proposal digest, a separate
approved record with `external_write_allowed=true`, and a Resource Binding with
`notes.write` scope. It rejects unsafe paths and symlinks, rechecks the target
digest before atomic replacement, and compares the actual written bytes before
returning `opl-persona-obsidian-apply-receipt.v1`. This library API and its tests
do not establish a public CLI/App apply action or a configured private vault.

## Host Boundary

OPL Framework owns the Host for runtime, Package graph, and App projection.
Studio owns its separate DSH application-host composition; the two scopes
collaborate through public contracts and do not share internal registries or
currentness. Persona contributes its Python `app-contribution` ABI through the
Framework boundary and does not create another Host or lifecycle manager.
App consumption and review requirements belong to
[App Integration](app-integration.md).

## Current Resource Binding

The private binding store is
`<profile>/data/persona/resource-bindings.json`. It holds opaque refs, scopes,
policy metadata, and health metadata; it never holds credentials or authority
content. The current CLI can set and check only an Obsidian directory binding,
with `knowledge.obsidian.v1` or `knowledge.documents.v1` as the capability. The
health check proves directory reachability only. `bindings.py` owns
`opl-persona-resource-binding.v1` and `opl-persona-resource-health.v1`; health
values are `healthy`, `degraded`, `unavailable`, or `unknown`. A stored health
observation must not be used as a fresh authorization or content readback.

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
