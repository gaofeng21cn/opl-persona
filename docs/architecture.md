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

Framework owns the shared Profile Workspace selector, marker and initialization
mechanics in `python/opl_framework/profile_workspace.py`. The installed Persona
carrier includes its byte-for-byte generated `_opl_profile_workspace.py`, so
workspace initialization has no Framework Python dependency. Derived knowledge
validation calls the installed Framework CLI. Persona retains its templates,
note-adapter resource bindings and private state. Regenerate the module with Framework's
`scripts/materialize-python-support.mjs --module profile_workspace --target
plugins/opl-persona/runtime/opl_persona/_opl_profile_workspace.py`; run
`OPL_FRAMEWORK_ROOT=<framework-checkout> make test` to check the projection bytes.

Persona is a judgment and proposal layer. It does not become a second mail
store, knowledge vault, or website CMS.

| Surface | Authority |
| --- | --- |
| OPL Relay | mail identities, raw mail evidence, memory evidence, drafts, send receipts |
| User-selected knowledge source | canonical personal notes and profile values in Obsidian or a normal Markdown directory |
| `gflab_web` | public publication/news content and deployment |
| OPL Persona | derived PI context, source-version dependencies, proposal shape, approval state |

The family-wide source, scope and lifecycle rules belong to the
[Framework knowledge source and memory policy](https://github.com/gaofeng21cn/one-person-lab/blob/main/docs/policies/knowledge-source-and-memory-policy.md).
Framework owns common source registration, grants, resolution and validity
checks. Persona is a consumer of those mechanisms, not a mandatory gateway for
other agents or another canonical personal knowledge store.

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
`context.select` persists the mode; `context.update` requires its current digest,
source refs and `source_versions`. Modes guide drafting, not permission. The
contexts read returns `active_context` assembled from approved memories whose
source dependencies remain valid. `person.update` and `memory.update` require
`expected_digest=absent` for creation or the current digest for replacement,
and the same source-version binding. A memory edit always resets it to `candidate`.
`memory.review` binds memory identity/digest, a user review ref, and a decision
(`approved`, `candidate`, `forgotten`). Management defaults to candidate and
approved entries; `status=all` includes forgotten records. This review state
does not replace a fresh source check.

`source_versions` is a non-empty object mapping accepted knowledge identities
to exact `sha256:...` revisions. For people, memories and customized modes,
Persona stores a derived summary plus these dependencies in
`opl-persona-workspace.v2`. It delegates source validation to:

```bash
opl knowledge verify-dependencies --workspace <Profile> --domain persona \
  --dependencies <array-json-file> --json
```

The private input array contains `{knowledge_id, sha256}` objects; the returned
verdict is body-free. Approval and context assembly require current, authorized
source versions. Missing, expired, drifted or revoked dependencies exclude the
derived item and appear in `excluded_knowledge`. An unavailable verifier also
excludes the item. Management views hide invalid summary content while keeping
the stored record available for repair; they do not delete the original record.
Built-in product modes are checked against their shipped content and do not
require personal-source bindings.

New independent preferences must first be accepted in the user's selected
canonical source, then referenced by Persona. A textual `source_ref` alone is
provenance, not proof of source currentness or permission. Resource Bindings
for note adapters do not substitute for Framework knowledge grants.

`workspace-migrate` performs the explicit one-time v1 to v2 conversion. It
backs up the original JSON, preserves records, and marks non-product records
for source review. Existing approvals cannot admit those records into current
context until their source dependencies have been supplied and checked.

Relay mail memory is read through `opl app contribution read --package-id
opl-relay` at `personal.memory.v1#people` and `#search`, with the same Profile
selector. Approved bounded evidence is not persisted by Persona. Missing Relay
availability is a local diagnostic in a ready Persona read model; there is no
database fallback. Cross-source derived state lives in `data/persona/workspace.json`.
Names and aliases alone do not automatically merge source identities.
Persona requires Relay's `source_policy.source_currentness_checked` and
`only_approved_memory_included` claims, then checks each approved summary's
`source_currentness` record. Stale summaries are excluded; currentness metadata
is preserved in the projection instead of treating approval as permanent validity.

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

Knowledge-dependent proposal rows retain their exact `payload.source_versions`
and expose a fresh `source_verification`. Approval rechecks those dependencies;
a stale proposal remains historical review evidence but cannot gain approval
until its source interpretation is regenerated. The Obsidian author adapter
does not accept a new Framework knowledge revision: editing a registered note
changes its bytes, so the resolver requires a separate `review-source` readback
before the revised note can enter current context.

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

An authorized maintainer may perform the review and record existing user
authority when it covers the exact target and payload. This does not require
repeated confirmation; missing or expanded authority does. Semantic acceptance,
the adapter's resource grant and the final readback remain distinct records.

## Inbox and Obsidian proposal contracts

`mail.triage` consumes one validated Relay facts envelope, an agent assessment
bound to the same email reference, and Persona's private policy/context
snapshots. The refs-only `data/persona/knowledge-inputs.json` maps the four
roles `identity`, `team`, `projects`, and `mail_policy` to accepted Framework
knowledge IDs. All selected sources pass the current-source reader; existing
files may be registered in place. It validates the decision and produces a
reviewable proposal and a refs-only
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
content. The CLI can set and check `obsidian` directory bindings using
`knowledge.obsidian.v1` or `knowledge.documents.v1`, and `markdown` directory
bindings using `knowledge.documents.v1`. The health check proves directory
reachability only. The existing note writer remains an Obsidian-specific owner
adapter; a Markdown directory binding does not invent another write action.
`bindings.py` owns
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

`setup init` creates control directories and handling policies. It leaves
personal identity and preference bodies untouched; `--local-knowledge`
explicitly creates missing local templates when this workspace is the chosen
canonical home. Existing external sources stay in place. Setup readiness has
the scope `runtime_configuration` and does not claim complete personal data,
valid knowledge grants or business readiness.

CLI mutations, including setup and binding changes, share
`data/persona/.workspace.lock`. POSIX uses `flock`; Windows uses a stable
single-byte `msvcrt` lock. Read/modify/write runs entirely under this lock;
JSON saves fsync the temporary file and atomically replace the destination,
with directory fsync on POSIX. Atomicity is per file, not a transaction spanning
the proposal and Inbox files. A failed staging attempt can be replayed
idempotently. An interrupted external apply before receipt persistence requires
owner reconciliation; it is not reported as applied or blindly retried.
