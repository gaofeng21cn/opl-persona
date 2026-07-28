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

`mail.triage` is a policy-bound interpretation of one or more stable
`email-store://` source references. It records a classification, priority,
rationale, uncertainty, recommended action, policy references, and an exact
policy digest. It also emits a generic `personal.inbox.v1` capture proposal so
that an App can show a cross-domain inbox without becoming a second mailbox.
Missing mail or policy provenance fails closed.

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

`OPL_PERSONA_HOME` is the private data root and `OPL_PERSONA_WORKSPACE` is the
replaceable human context. When unset, Persona uses `~/.opl-persona` and its
`workspaces/default` child. The repository, installed plugin, and Package are
never data authorities.
