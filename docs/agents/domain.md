# Domain Docs

How the engineering skills should consume this repo's domain documentation when exploring the codebase.

## Before exploring, read these

- **`CONTEXT.md`** at the repo root: contains the authoritative domain terminology and boundaries.
- **`docs/adr/`**: read ADRs that touch the area you're about to work in.
- **`docs/configuration-migration.md`**: read when changing configuration ownership, endpoint setup, Schedule persistence, or upgrade migration.

If any of these files don't exist, **proceed silently**. Don't flag their absence; don't suggest creating them upfront. The `/domain-modeling` skill creates them lazily when terms or decisions actually get resolved.

## File structure

Single-context repo:

```
/
├── CONTEXT.md
├── docs/adr/
│   ├── 0001-explicit-configuration-ownership.md
│   ├── 0002-retire-file-tree-feature.md
│   ├── 0003-managed-rclone-configuration.md
│   ├── 0004-dedicated-gdrive-to-nextcloud-scope.md
│   ├── 0005-separate-execution-inspection-configuration.md
│   ├── 0006-single-control-process-vm-topology.md
│   ├── 0007-durable-schedule-and-sync-run-lifecycle.md
│   └── 0008-sixty-day-history-retention.md
└── app/
```

## Use the glossary's vocabulary

When your output names a domain concept (in an issue title, a refactor proposal, a hypothesis, a test name), use the term as defined in `CONTEXT.md`. Don't drift to synonyms the glossary explicitly avoids.

If the concept you need isn't in the glossary yet, that's a signal: either you're inventing language the project doesn't use (reconsider) or there's a real gap (note it for `/domain-modeling`).

## Flag ADR conflicts

If your output contradicts an existing ADR, surface it explicitly rather than silently overriding:

> _Contradicts ADR-0004 (dedicated-gdrive-to-nextcloud-scope), but worth reopening because..._
