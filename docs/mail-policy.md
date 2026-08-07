# Persona Mail Policy Boundary

Owner: `opl-persona`
Purpose: `persona_mail_policy_boundary`
State: `active_current`
Machine boundary: 当前行为归 `plugins/opl-persona/runtime/opl_persona/policy.py`、`core.py`、`plugins/opl-persona/opl-package.json` 与 `tests/test_policy.py` / `tests/test_core.py`。本文不能证明私有 Profile Workspace 可用、Plugin/Package installed current、App 已消费贡献或任何 mailbox mutation；邮件事实、草稿、发送和最终回读仍归 Relay 与邮件 owner。

OPL Persona owns the interpretation of mail rules. The user's rules are
Markdown files in the configured Profile Workspace, normally:

```text
<profile>/
└── policies/
    ├── mail-triage.md
    ├── journal-review-policy.md
    └── manuscript-status-policy.md
```

The files are private runtime data. They must not be copied into this
repository, a Package cache, or an App read model. Relay remains the authority
for mailbox facts, stable `email-store://` identities, drafts, sends, and
receipts. Relay provides a facts-only `opl-relay-mail-triage-evidence.v2`
bridge. Its policy digest is a refs-set provenance value, never the Markdown
content digest.

## Snapshot contract

`opl_persona.policy.load_markdown_policies()` reads every Markdown file below
the selected Profile Workspace's `policies/` directory. Triage does not accept
external policy paths, external content digests, or a partial policy selection.
The snapshot records:

- canonical `policy://persona/...` refs;
- the selected file content;
- a `sha256:` digest over ordered workspace-relative paths and file bytes.

`mail.triage` proposals carry this content digest as `policy_digest` and mark
it with `policy_digest_kind: "content"`. Missing local Markdown fails closed.
Persona preserves Relay's independently validated refs-set digest only as
provenance metadata.

## Triage evidence

The triage input is exactly one `relay_evidence` object. Persona validates its
canonical `email-store://` identity, nested `mail.headers`, parsed recipient
facts, raw-message hashes, freshness, Relay policy ref digest, and write
boundary before using it. Persona then loads its own mail identity and
manuscript/roster context from `<profile>/profile/*.md` and
`<profile>/context/*.md`, records a separate content digest, and returns
normalized `to`, `cc`, and `bcc` facts plus conservative routing fields. When
actual-first-author or team evidence is not available, those fields remain
uncertain rather than being invented:

- only the user is a recipient and the first author matches a team member:
  propose forwarding to that first author;
- the first author is already a recipient: notify the user and identify the
  current follow-up owner;
- advertising and mass marketing remain cleanup candidates, but no mailbox
  mutation is executed by Persona.

All proposals retain `source_refs` and
`approval.external_write_allowed: false`. Relay or another domain owner must
perform any approved external operation and read back the authoritative result.
