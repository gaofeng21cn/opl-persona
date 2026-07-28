# Persona Mail Policy Boundary

OPL Persona owns the interpretation of mail rules. The user's rules are
Markdown files in the configured Profile Workspace, normally:

```text
$OPL_PROFILE_WORKSPACE/
└── policies/
    ├── mail-triage.md
    ├── journal-review-policy.md
    └── manuscript-status-policy.md
```

The files are private runtime data. They must not be copied into this
repository, a Package cache, or an App read model. Relay remains the authority
for mailbox facts, stable `email-store://` identities, drafts, sends, and
receipts. Relay may provide its own `relay_policy_digest` for a refs-set
snapshot, but Persona never treats that value as the Markdown content digest.

## Snapshot contract

`opl_persona.policy.load_markdown_policies()` selects explicit policy refs or
paths, or all Markdown files below `policies/` when no selection is supplied.
The snapshot records:

- canonical `policy://persona/...` refs;
- the selected file content;
- a `sha256:` digest over ordered workspace-relative paths and file bytes.

`mail.triage` proposals carry this content digest as `policy_digest` and mark
it with `policy_digest_kind: "content"`. A stale supplied digest fails closed.
When a Relay bridge supplies `policy_digest_kind: "refs_set"` (or
`relay_policy_digest`), Persona reloads its own workspace and retains the Relay
value only as provenance metadata.

## Triage evidence

The triage input may include normalized `to`, `cc`, and `bcc` addresses,
`user_addresses`, the actual article first author, a lab/team roster, and the
current follow-up owner. Persona returns those facts in the reviewable
proposal and derives conservative routing suggestions:

- only the user is a recipient and the first author matches a team member:
  propose forwarding to that first author;
- the first author is already a recipient: notify the user and identify the
  current follow-up owner;
- advertising and mass marketing remain cleanup candidates, but no mailbox
  mutation is executed by Persona.

All proposals retain `source_refs` and
`approval.external_write_allowed: false`. Relay or another domain owner must
perform any approved external operation and read back the authoritative result.
