# OPL Persona Documentation

Family-wide documentation lifecycle rules live in the [OPL docs lifecycle policy](https://github.com/gaofeng21cn/one-person-lab/blob/main/docs/policies/docs-lifecycle-policy.md). This index assigns one responsibility per document in `opl-persona` and separates **current implementation** from **target design**.

| Document | State | Sole responsibility |
| --- | --- | --- |
| [English README](../README.md) / [中文 README](../README.zh-CN.md) | Current entry | Product summary, local CLI/Codex installation, verification commands, and package distribution overview |
| [Repository agent rules](../AGENTS.md) | Current rules | Maintainer boundaries, memory/proposal invariants, and doc maintenance rules |
| [Architecture](architecture.md) | Current implementation | Owner split, exported surfaces, collection read-model, proposal/Inbox/Obsidian/Binding contracts, resumable tasks, connector contract, and runtime lock |
| [External Professional Work](external-professional-work.md) | Current handbook | Step-by-step setup and recovery for resumable tasks, browser/desktop tools, GitHub labels, and connector packages |
| [Mail Policy](mail-policy.md) | Current implementation | Mail policy role mapping, snapshot digest, triage evidence boundary, and drafting feedback evaluation |
| [App Integration](app-integration.md) | Current boundary | Role-neutral OPL App consumption, approval projection, and cross-domain confirmation rules |
| [Distribution](distribution.md) | Current boundary | Codex Plugin marketplace, `make install-local` launcher modes, and GHCR OCI publication boundary |
| [Architecture Guidance](architecture-guidance.md) | Target design | Cross-repository target boundaries, composable Capability/Adapter/Binding/Recipe model, and external-portal target scope |
| [Personal Profile & Form Fill](personal-profile-form-fill.md) | Target design | Target `personal_field.v1` field catalog, form-fill proposal/receipt schema, and adapter boundary |

Target-design documents do not create callable CLIs, schemas, or installed runtime guarantees; current machine truth lives in `plugins/opl-persona/opl-package.json`, runtime modules, and `tests/`.
