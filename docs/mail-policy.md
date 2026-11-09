# Persona Mail Policy Boundary

Owner: `opl-persona`
Purpose: `persona_mail_policy_boundary`
State: `active_current`
Machine boundary: 当前行为归 `plugins/opl-persona/runtime/opl_persona/policy.py`、`knowledge.py`、`core.py`、`plugins/opl-persona/opl-package.json` 与 `tests/test_policy.py` / `tests/test_core.py`。本文不能证明私有 Profile Workspace 可用、Plugin/Package installed current、App 已消费贡献或任何 mailbox mutation；邮件事实、草稿、发送和最终回读仍归 Relay 与邮件 owner。

OPL Persona interprets mail rules from the user's selected canonical knowledge
sources. Rules, identity facts, team records, and project context may live in
Obsidian or an ordinary directory. Framework owns their registration, accepted
revisions, and access grants under the shared
[knowledge source and memory policy](https://github.com/gaofeng21cn/one-person-lab/blob/main/docs/policies/knowledge-source-and-memory-policy.md).
Persona keeps role references in the Profile; it does not require another copy
of the personal source documents.

Relay owns mailbox facts, stable `email-store://` identities, drafts, sends,
and receipts. Its facts-only `opl-relay-mail-triage-evidence.v2` bridge carries
a refs-set provenance digest, not a policy content digest.

## Source selection

`<profile>/data/persona/knowledge-inputs.json` selects knowledge identities for
four roles. This file contains references only:

```json
{
  "schema_version": "opl-persona-knowledge-inputs.v1",
  "roles": {
    "identity": ["owner.identity"],
    "team": ["owner.team"],
    "projects": ["owner.projects"],
    "mail_policy": ["owner.mail-policy"]
  }
}
```

Only these role names and lists of unique knowledge IDs are accepted. An empty
or omitted `identity`, `team`, or `projects` role means that those facts are
unavailable. Mail triage requires at least one `mail_policy` ID. Source roots,
grants, paths, and document content belong in neither this file nor a Resource
Binding substitute. Framework follows `shared/memory/knowledge-bindings.json`
to the selected `registry_ref` and validates the caller's access. The Profile's
`data/knowledge-sources.json` is one possible location, not an implicit registry.

Existing files may remain in `profile/`, `context/`, and `policies/` or in the
user's external knowledge directory. Register and accept them in place through
the Framework source workflow, then select their IDs here. Setup's policy
templates are not automatically accepted sources. Directory presence alone
does not authorize or supply policy or personal context.

## Snapshot contract

`opl_persona.policy.load_markdown_policies()` reads every source selected for
`mail_policy` through Framework's `knowledge read-source` boundary. The reader
validates current source identity, grants, and accepted revision, then Persona
checks the returned content's SHA-256. A missing selection or invalid selected
source stops triage; it never falls back to a local file or silently omits a
selected rule.

Each snapshot records the selected knowledge IDs, source refs, exact source
revision hashes, and content. The composite content digest covers ordered role,
knowledge ID, revision, and content values. Ordering is deterministic and
relocating the Profile does not change the digest. Snapshot metadata exposes
source identities and revisions without source bodies or invented file paths.

`mail.triage` proposals carry this digest as `policy_digest` with
`policy_digest_kind: "content"`. Proposals also retain `policy_source_versions`
and `context_source_versions` maps from knowledge ID to exact SHA-256 revision;
their union is stored in `payload.source_versions` for dependency verification.
A shared knowledge ID read at conflicting revisions stops proposal creation.
All version maps are bound by the proposal digest without retaining source
bodies. Persona retains Relay's independently
validated refs-set digest separately as provenance metadata.

## Triage evidence

Triage accepts exactly one `relay_evidence` object and one evidence-bound
`assessment` object supplied by the calling agent. Persona validates the
canonical `email-store://` identity, nested `mail.headers`, parsed recipient
facts, raw-message hashes, freshness, Relay policy-ref digest, and write
boundary before using it.

Persona then reads selected `identity`, `team`, and `projects` sources through
the same Framework boundary. Identity sources use Markdown fields such as
`- addresses: person@example.org`; team sources use three-column name, role,
and email tables; project sources use `##` sections with fields such as
`actual first author` and `verified routing address`. Role selection determines
how a source is interpreted, rather than its filename. The context snapshot
has its own content digest and source refs.

Persona returns normalized `to`, `cc`, and `bcc` facts plus conservative routing
fields. It validates the assessment's classification, priority, rationale,
uncertainty, recommended action, and exact email reference. The calling agent
reads the private policy and correspondence before judging meaning; the Python
engine does not classify a message by keywords. Missing author or team facts
remain uncertain:

- only the user is a recipient and the first author matches a team member:
  propose forwarding to that first author;
- the first author is already a recipient: notify the user and identify the
  current follow-up owner;
- advertising and mass marketing may be proposed for cleanup after contextual
  judgment; Persona produces the proposal.

All proposals retain `source_refs` and
`approval.external_write_allowed: false`. Relay or another domain owner
performs any authorized external operation and reads back its result.
