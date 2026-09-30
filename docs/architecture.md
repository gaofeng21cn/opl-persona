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

The App contribution ABI exposes six data refs. The
Persona-owned read-model store serves both `personal.context.v1#today` and
`personal.inbox.v1#recent` as refs-only projections: `today` includes active
(`staged` or `routed`) Inbox entries, while `recent` includes all entries. The
projection contains bounded summaries and opaque source refs, never source
content. `workspace.py` adds working modes, derived people, and evidence memory;
`proposals.py` persists proposals, review decisions and owner receipts. Read refs:

```text
personal.context.v1#today
personal.context.v1#contexts
personal.context.v1#proposals
personal.memory.v1#people
personal.memory.v1#memories
personal.inbox.v1#recent
```

Working modes are `academic-mail`, `technical-memo`, `academic-website`, and
`research-writing`, with localized labels/summaries, guidance, provenance and digests.
`context.select` persists the mode; `context.update` requires its current digest
and source refs. Modes guide drafting, not permission. The contexts read returns
`active_context` assembled from approved memories only. `person.update` and
`memory.update` require `expected_digest=absent` for creation or the current
digest for replacement. A memory edit always resets it to `candidate`.
`memory.review` binds memory identity/digest, a user review ref, and a decision
(`approved`, `candidate`, `forgotten`). Management defaults to candidate and
approved entries; `status=all` includes forgotten records.

Relay mail memory is read through `opl app contribution read --package-id
opl-relay` at `personal.memory.v1#people` and `#search`, with the same Profile
selector. Approved bounded evidence is not persisted by Persona. Missing Relay
availability is a local diagnostic in a ready Persona read model; there is no
database fallback. Cross-source derived state lives in `data/persona/workspace.json`.
Names and aliases alone do not automatically merge source identities.

### Collection read-model

All six reads declare `query`, `status`, `offset` and `limit` in their returned
`input_schema`. Query is a case-insensitive substring search over presentation,
identity, provenance and proposal payload fields; an empty query clears search.
Status options are collection-specific: contexts and people have no review
state and accept `all`; memories default to `active` (candidate and approved),
proposals and recent Inbox default to `all`, and today retains its active Inbox
boundary. The contexts read also retains `context_id` and `person_id` selectors.
Filtering runs over the complete Persona collection and supplied public Relay
evidence projection before paging, never just over the returned page. This does
not enumerate or copy Relay's private store. Approved-only context assembly is
independent of collection search, status filters and pagination.

Offset and limit are strict integers, excluding booleans, with minima 0 and 1;
defaults are 0 and 50. `data.pagination` is
`{offset, limit, total, has_more}`, where total counts filtered matches before
paging and `data.count` counts returned rows. Empty and out-of-range pages
retain schemas, diagnostics and collection actions. Ordering follows each
owner's existing collection order.

Every collection returns explicit
`data.collection_actions:[{action_ref,input,label_i18n}]`, including an empty
array where no collection command applies. Only creation/proposal builders
appear here; row inspect, review, update, select, authorize and apply remain in
`items[].actions`. A collection create and a row update may use the same ref;
consumers must not hide the create action because that ref occurs on a row.
`data.command_inputs` retains declared action schemas and creation defaults.
Person/memory creates bind a fresh response-local UUID in `person_id`/`memory_id`
and `expected_digest="absent"`; generating these defaults creates no persisted
record. Optional association/alias lists default to empty. Note proposals
default to create/absent with empty frontmatter, links and tags; capture defaults
to kind `note`. Consumers use the explicit action input over command defaults,
keep technical identity/digest bindings out of editable user fields, and never
replace row identity/digest with creation defaults. User review references and
separate external confirmation remain explicit inputs, not inferred approvals.

Proposal rows include
`preview:{title,target,body,before,after,evidence_refs}`. Target is the relative
note path or explicit owner target; body is proposed text or a structured-payload
JSON presentation. Note after is the exact Markdown produced by the existing
owner renderer, including frontmatter, tags, links and evidence. Other after
values are the proposed payload object. Before is `null` unless the exact update
target is safely readable through a compatible Obsidian `notes.read` binding
and its bytes match the target's expected digest. A single compatible binding
can be used before authorization; multiple bindings require the proposal's
resource-bound external authorization to select one. Missing, unreadable,
non-UTF-8, symlinked, stale or rebound targets remain `null`; no source reference
is dereferenced to invent a diff. Preview is computed only for returned rows,
never persisted, and confers no write authority. Obsidian authorize/apply still
belongs to the existing Persona owner adapter with its independent review,
resource binding and exact-digest checks.

All CLI proposal builders and the existing three App propose actions persist
to `data/persona/proposals.json`. Capture/triage also stage Persona-local Inbox
captures through `inbox.py`. Replaying identical proposals preserves review
state. A changed pending candidate replaces the old candidate; changed reviewed
identities are rejected. Inspect returns the complete proposal. Approve/reject
require `proposal_id + approval_ref + expected_digest` and persist decisions.
Approval never grants external write, mail send, or website publish.

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
current SHA-256 digest for update. Proposal generation does not apply notes.
The separate owner adapter in `obsidian_apply.py` implements
`apply_approved_obsidian_note`: it requires an exact proposal digest, a separate
approved record with `external_write_allowed=true`, and a Resource Binding with
`notes.write` scope. It rejects unsafe paths and symlinks, rechecks the target
digest before atomic replacement, and compares the actual written bytes before
returning `opl-persona-obsidian-apply-receipt.v1`. Public
`knowledge.obsidian.v1#note.authorize` takes proposal identity/digest, binding id,
a distinct approval ref, and `confirmation=confirmed`. It persists an independent
scope-bound approval without writing a note. `#note.apply` requires the same
identity/digest/binding and exactly one of `external_approval_ref` (persisted
grant) or `external_approval` (explicit object). The object binds proposal digest,
binding id, provider, capability, resource ref and `scope=notes.write`, with
`status=approved` and `external_write_allowed=true`. Rebinding invalidates the
grant. Successful readback is stored with the proposal; repeated apply points
to the existing receipt instead of re-executing. No send/publish is exported.

Convenience CLI routes share the ABI: `context list/select/update`,
`people list/update`, `memory list/update/review`, and
`proposal list/inspect/approve/reject/authorize-obsidian/apply-obsidian`.
Writes take JSON through `--input <file-or->`; list accepts optional input.

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

CLI mutations, including setup and binding changes, share
`data/persona/.workspace.lock`. POSIX uses `flock`; Windows uses a stable
single-byte `msvcrt` lock. Read/modify/write runs entirely under this lock;
JSON saves fsync the temporary file and atomically replace the destination,
with directory fsync on POSIX. Atomicity is per file, not a transaction spanning
the proposal and Inbox files. A failed staging attempt can be replayed
idempotently. An interrupted external apply before receipt persistence requires
owner reconciliation; it is not reported as applied or blindly retried.
