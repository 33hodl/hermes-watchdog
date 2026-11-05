# Closed to get under the repo's 5-open-PR contributor cap

`NousResearch/hermes-agent` caps contributors without write access at 5 open pull requests
([cli/cli#14874](https://github.com/cli/cli/issues/14874)). 24 were open, so the 20 oldest were closed on 2026-11-05 to make room
for the `hermes-watchdog` plugin-catalog PR.

Branches are untouched. Reopen any of them with:

```bash
gh pr reopen <N> --repo NousResearch/hermes-agent
```

| PR | opened | title | branch |
|---|---|---|---|
| #86048 | 2026-08-14 | fix(doctor): warn instead of crash on unreadable memory files | `pr-doctor-memory-read-guard` |
| #89009 | 2026-08-18 | fix(gateway): spawn the updater in its own systemd transient unit | `pr-update-spawn-transient-unit` |
| #89008 | 2026-08-18 | fix(gateway): fail fast when the update process dies without an exit code | `pr-update-dead-updater-fail-fast` |
| #92127 | 2026-08-22 | fix(checkpoints): recover from stale git locks in the shadow store | `pr-checkpoint-stale-lock-repair` |
| #92829 | 2026-08-23 | fix(desktop): opening a non-active-profile session leaves its unread dot | `fix/desktop-unread-ack-cross-profile-marker` |
| #94302 | 2026-08-24 | fix(file-sync): skip permission-denied host files instead of wedging the sync cycle | `fix/file-sync-unreadable-skip` |
| #100332 | 2026-09-01 | fix(gateway): refuse inbound turns on stale code instead of ImportError crash | `pr-turn-path-skew-guard` |
| #109599 | 2026-09-13 | fix(gateway): suppress emphasis-wrapped silence markers in the autonomous lane | `pr-autonomous-silence-emphasis` |
| #110554 | 2026-09-14 | fix(agent): guard the sequential tool submit against interpreter shutdown | `pr-sequential-tool-shutdown-guard` |
| #112556 | 2026-09-16 | docs(cli): document the five undocumented hermes skills subcommands | `pr-docs-skills-subcommands` |
| #112555 | 2026-09-16 | docs(cli): document the five undocumented hermes sessions subcommands | `pr-docs-sessions-subcommands` |
| #112553 | 2026-09-16 | docs(cli): document the six undocumented hermes update flags | `pr-docs-update-flags` |
| #117870 | 2026-09-21 | fix(doctor): local-models runtime diagnostics (#117326, slice 3) | `pr-local-runtime-doctor-diagnostics` |
| #118806 | 2026-09-22 | fix(auth): surface elapsed state on Nous device-code timeout (#98682) | `pr-98682-device-flow-elapsed-timeout` |
| #122569 | 2026-09-25 | fix(update): refuse source updates when npm/runtime trees are foreign-owned | `fix/update-ownership-guard-node-modules` |
| #123773 | 2026-09-26 | fix(pm): anchor mcp/homeassistant/sms/uvloop extras so legacy venv migration carries them | `pr-pm-anchors-mcp-extra` |
| #133102 | 2026-10-05 | fix(checkpoints): skip an untraversable working dir instead of logging a git traceback | `pr-checkpoint-inaccessible-workdir` |
| #133692 | 2026-10-06 | fix(agent): re-fold the active /goal and its contract at the compaction boundary | `pr-goal-refold` |
| #134300 | 2026-10-07 | docs(cli): correct the `hermes doctor` and `hermes logs` option lists | `pr-docs-doctor-logs-options` |
| #134299 | 2026-10-07 | docs(cli): document the missing `hermes cron` subcommands | `pr-docs-cron-subcommands` |

## Left open

| PR | opened | title | branch |
|---|---|---|---|
| #134298 | 2026-10-07 | docs(cli): list the five missing top-level commands and document `hermes verify` | `pr-docs-missing-top-level-commands` |
| #135986 | 2026-10-10 | fix(plugins): disk-cleanup never deletes protected or out-of-scope tracked paths | `pr-disk-cleanup-protected-scope` |
| #136959 | 2026-10-12 | fix(mcp): a shutdown-race scheduling error is teardown, not a server failure | `pr-mcp-shutdown-scheduling-park` |
| #140325 | 2026-10-17 | fix(doctor): state.db repair hints order "stop the profile's gateway" before --fix (#110054) | `pr-doctor-repair-hint-holder-guard` |
