# OPL Persona Architecture

## Owner split

Persona is a judgment and proposal layer. It does not become a second mail
store, knowledge vault, or website CMS.

| Surface | Authority |
| --- | --- |
| OPL Relay | mail identities, raw mail evidence, memory evidence, drafts, send receipts |
| Obsidian | private notes and memo content |
| `gflab_web` | public publication/news content and deployment |
| OPL Persona | shared PI context, provenance, proposal shape, approval state |

## v1 contract

The only cross-system write primitive is a reviewable proposal:

```text
publication -> knowledge.ingest + website.publication
Obsidian memo -> website.article + mail.draft_context
```

Each proposal contains a stable id, an explicit target, payload, source
references, and `approval.external_write_allowed=false`. An adapter can execute
only an exact user-approved proposal. A proposal is not a published website
change, sent email, or written vault note.

## Runtime data

`OPL_PERSONA_HOME` is the private data root and `OPL_PERSONA_WORKSPACE` is the
replaceable human context. When unset, Persona uses `~/.opl-persona` and its
`workspaces/default` child. The repository, installed plugin, and Package are
never data authorities.
