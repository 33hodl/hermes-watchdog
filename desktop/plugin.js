/**
 * Hermes Watchdog — Desktop half.
 *
 * Three surfaces over the plugin's own backend (`ctx.rest` -> /api/plugins/hermes-watchdog/*),
 * which is the same engine the `watchdog_status` / `watchdog_repair` tools and the
 * `on_session_end` hook use. Nothing here talks to Hermes internals directly.
 *
 * The sidebar page is the primary door: a docked `panes` contribution only shows in a
 * layout that has a right zone, so the page route works on every layout.
 */

import {
  Badge,
  Button,
  Codicon,
  EmptyState,
  GlyphSpinner,
  ScrollArea,
  StatusDot,
  cn,
  host,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const ROUTES_AREA = 'routes'
const SIDEBAR_NAV_AREA = 'sidebar.nav'
const PAGE_PATH = '/watchdog'

const TONE = { ok: 'good', degraded: 'warn', critical: 'bad', unknown: 'muted' }
const HEALTH_LABEL = {
  ok: 'All clear',
  degraded: 'Needs a look',
  critical: 'Needs a look',
  unknown: 'Not sure yet'
}

// Jargon out: a person reading the pane should not need to know what Hermes calls
// each failure class.
const PLAIN_CAUSE = {
  timeout: 'It ran too long and was stopped.',
  delivery: 'The message it sends did not go out.',
  agent: 'The assistant hit an error while running it.',
  script: 'Its script exited with an error.',
  auth: 'It could not sign in to something it needs.',
  config: 'Its settings are wrong or missing.',
  interrupted: 'It was stopped before it finished — the machine slept, or Hermes restarted.',
  unknown: 'Hermes recorded a failure but no details.'
}

/** A job id is not a name a person can act on. */
function jobLabel(jobName, jobId) {
  if (jobName && jobName !== jobId) {
    return jobName
  }
  return 'A job that no longer exists'
}

function plainCause(incident) {
  const error = String((incident && incident.error) || '').toLowerCase()
  if (error.includes('interrupt')) {
    return PLAIN_CAUSE.interrupted
  }
  return PLAIN_CAUSE[(incident && incident.failure_type) || 'unknown'] || PLAIN_CAUSE.unknown
}
const OUTCOME_TONE = { repaired: 'good', failed: 'bad', escalated: 'warn', running: 'muted' }

const POLL_MS = 15000
const KEY = ['hermes-watchdog', 'status']

function checked(ts) {
  if (!ts) {
    return ''
  }
  const seconds = Math.max(0, Math.round(Date.now() / 1000 - Number(ts)))
  if (seconds < 90) {
    return 'checked just now'
  }
  if (seconds < 3600) {
    return 'checked ' + Math.round(seconds / 60) + ' min ago'
  }
  if (seconds < 86400) {
    return 'checked ' + Math.round(seconds / 3600) + ' h ago'
  }
  return 'checked ' + Math.round(seconds / 86400) + ' d ago'
}

function relative(ts) {
  if (!ts) {
    return ''
  }

  const seconds = Math.max(0, Math.round(Date.now() / 1000 - Number(ts)))

  if (seconds < 60) {
    return seconds + 's ago'
  }

  if (seconds < 3600) {
    return Math.round(seconds / 60) + 'm ago'
  }

  if (seconds < 86400) {
    return Math.round(seconds / 3600) + 'h ago'
  }

  return Math.round(seconds / 86400) + 'd ago'
}

function absolute(ts) {
  if (!ts) {
    return ''
  }
  const at = new Date(Number(ts) * 1000)
  return Number.isNaN(at.getTime()) ? '' : at.toLocaleString()
}

function useWatchdog(ctx) {
  return useQuery({
    enabled: Boolean(ctx && ctx.rest),
    queryFn: () => ctx.rest('/status'),
    queryKey: KEY,
    refetchInterval: POLL_MS,
    retry: false
  })
}

function Chip({ ctx }) {
  const { data } = useWatchdog(ctx)
  const incidents = (data && data.counts && data.counts.open_incidents) || 0
  const health = (data && data.health) || 'unknown'

  // Clickable: the chip is the one surface present on every layout, so it is the
  // guaranteed door to the page when a layout has no right zone (or a client build
  // predates the sidebar.nav area).
  // The status bar is for signals, not labels: say nothing while everything is fine.
  // The sidebar row is the always-present door to the page.
  if (incidents === 0) {
    return null
  }

  return jsxs('button', {
    className: cn('inline-flex h-full cursor-pointer items-center gap-1 px-1.5 text-[0.6875rem]',
      'text-(--ui-text-warning) hover:text-(--ui-text-primary)'),
    onClick: () => host.navigate(PAGE_PATH),
    title: incidents + ' scheduled job' + (incidents === 1 ? '' : 's') + ' need a look — open Watchdog',
    type: 'button',
    children: [
      jsx(StatusDot, { tone: TONE[health] || 'muted' }),
      jsx('span', { children: 'watchdog ' + incidents })
    ]
  })
}

function copyCommand(command) {
  const text = String(command || '')
  const done = () => {
    try {
      host.notify({ kind: 'success', message: 'Copied: ' + text })
    } catch (_) {
      // a missing notifier must not break the row
    }
  }
  try {
    navigator.clipboard.writeText(text).then(done, done)
  } catch (_) {
    done()
  }
}

const RUN_TONE = {
  completed: 'good', success: 'good', delivered: 'good',
  failed: 'bad', error: 'bad', timeout: 'bad',
  cancelled: 'warn', skipped: 'muted', running: 'muted'
}

/** Five runs in order: "failed once" and "failed every night since Tuesday". */
function RunStrip({ runs }) {
  if (!runs || runs.length === 0) {
    return null
  }
  return jsxs('div', {
    className: 'mt-1 flex items-center gap-1',
    children: [
      jsx('span', {
        className: 'text-[0.625rem] uppercase tracking-wide text-(--ui-text-quaternary)',
        children: 'last ' + runs.length + ' runs'
      }),
      runs.map((run, index) => jsx('span', {
        title: (run.status || 'unknown') + (run.at ? ' · ' + new Date(run.at).toLocaleString() : ''),
        children: jsx(StatusDot, { tone: RUN_TONE[run.status] || 'muted' })
      }, index))
    ]
  })
}

function fallbackDetail(incident) {
  // Never show an incident with nothing to do about it: if the running backend
  // predates `detail`, build the same four parts here from fields we always have.
  const name = jobLabel(incident.job_name, incident.job_id)
  const error = String(incident.error || '').trim()
  const what = name + ' failed'
    + (error ? ': ' + error.slice(0, 240)
             : '. Hermes stored no error text for it — the run\'s own output is the only detail.')
  const why = incident.job_id
    ? 'Watchdog has no repair it can prove worked for this failure, so it will not guess.'
    : 'The job behind this failure no longer exists, so there is nothing left to re-run.'
  const steps = []
  if (incident.job_id) {
    steps.push({ text: 'See the job and when it last ran', command: 'hermes cron show ' + incident.job_id })
    steps.push({ text: 'Fix the cause, then run it once by hand', command: 'hermes cron run ' + incident.job_id })
    steps.push({ text: 'Or stop it retrying on its own schedule', command: 'hermes cron pause ' + incident.job_id })
  }
  steps.push({ text: 'Press Done when you have handled it — it stays quiet until the same error returns' })
  return { what: what, tried: [], why: why, steps: steps }
}

function incidentDetail(incident) {
  const detail = (incident && incident.detail) || {}
  return detail.what ? detail : fallbackDetail(incident)
}

function IncidentDetail({ incident }) {
  const detail = incidentDetail(incident)
  const tried = detail.tried || []
  const steps = detail.steps || []
  return jsxs('details', {
    className: 'mt-1 text-xs leading-5 text-(--ui-text-secondary)',
    open: incident.state === 'alerted',
    children: [
      jsx('summary', {
        className: 'cursor-pointer select-none rounded text-(--ui-text-quaternary) hover:text-(--ui-text-tertiary) focus-visible:ring-1 focus-visible:ring-(--ui-stroke-secondary) focus-visible:outline-none',
        children: 'What happened, and what to do'
      }),
      jsxs('div', {
        className: 'mt-1.5 space-y-1.5 border-l border-(--ui-stroke-secondary)/50 pl-2',
        children: [
          jsx('div', { children: detail.what }),
          tried.length
            ? jsxs('div', {
                children: [
                  jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Already tried: ' }),
                  jsx('span', { children: tried.join(' · ') })
                ]
              })
            : null,
          jsxs('div', {
            children: [
              jsx('span', { className: 'text-(--ui-text-quaternary)', children: 'Why it stopped: ' }),
              jsx('span', { children: detail.why })
            ]
          }),
          steps.length
            ? jsxs('ol', {
                className: 'mt-1 list-decimal space-y-0.5 pl-4',
                children: steps.map((step, index) => jsxs('li', {
                  children: [
                    jsx('span', { children: step.text }),
                    step.command
                      ? jsx('button', {
                          className: 'ml-1 cursor-pointer rounded bg-(--ui-stroke-secondary)/30 px-1 py-0.5 font-mono text-[0.6875rem] text-(--ui-text-secondary) hover:text-(--ui-text-primary)',
                          title: 'Click to copy',
                          type: 'button',
                          onClick: () => copyCommand(step.command),
                          children: step.command
                        })
                      : null
                  ]
                }, index))
              })
            : null
        ]
      })
    ]
  })
}

function IncidentRow({ incident, onRepair, onAck, busy, compact }) {
  return jsxs('div', {
    className: cn('flex items-start gap-2 border-b border-(--ui-stroke-secondary)/40 px-3 last:border-b-0',
      compact ? 'py-2' : 'py-3'),
    children: [
      jsx(StatusDot, { className: 'mt-1.5', tone: 'bad' }),
      jsxs('div', {
        className: 'min-w-0 flex-1',
        children: [
          jsxs('div', {
            className: 'flex items-center gap-1.5',
            children: [
              jsx('span', {
                className: 'truncate text-xs font-medium text-(--ui-text-primary)',
                title: incident.job_id,
                children: jobLabel(incident.job_name, incident.job_id)
              })
            ]
          }),
          incident.detail && incident.detail.what
            ? null
            : jsx('div', {
                className: 'mt-0.5 line-clamp-2 text-[0.6875rem] leading-4 text-(--ui-text-tertiary)',
                children: plainCause(incident)
              }),
          jsx(RunStrip, { runs: incident.runs }),
          jsx(IncidentDetail, { incident })
        ]
      }),
      jsxs('div', {
        className: 'flex shrink-0 items-center gap-1',
        children: [
          (incident.detail && incident.detail.job_exists === false)
            ? null
            : jsx(Button, {
                disabled: busy,
                onClick: () => onRepair(incident.job_id),
                size: 'xs',
                variant: 'secondary',
                children: 'Try the fix again'
              }),
          (incident.detail && incident.detail.job_exists === false)
            ? null
            : jsx(Button, {
                onClick: () => host.navigate('/cron'),
                size: 'xs',
                variant: 'ghost',
                title: 'Open the Cron page to see this job and its runs',
                children: 'Open Cron'
              }),
          jsx(Button, {
            disabled: busy,
            onClick: () => onAck(incident.incident_id),
            size: 'xs',
            variant: 'ghost',
            title: 'Mark this handled — it stays quiet unless the same error comes back',
            children: 'Done'
          })
        ]
      })
    ]
  })
}

const PLAIN_OUTCOME = {
  repaired: 'Fixed',
  escalated: 'Handed to you',
  failed: 'Could not fix',
  running: 'Trying now'
}

/** 'Handed to you' is already the verdict; the detail should add, not repeat it. */
function tidyDetail(repair) {
  const detail = String(repair.detail || '').trim()
  if (!detail) {
    return ''
  }
  if (repair.outcome === 'escalated') {
    const inner = detail.replace(/^handed to the operator\s*/i, '').replace(/^\((.*)\)$/, '$1').trim()
    return inner === 'core incident marked alerted' ? 'marked in Hermes as needing you' : inner
  }
  return detail
}

function RepairRow({ repair, compact }) {
  return jsxs('div', {
    className: cn('flex items-start gap-2 border-b border-(--ui-stroke-secondary)/40 px-3 last:border-b-0',
      compact ? 'py-2' : 'py-3'),
    children: [
      jsx(StatusDot, { className: 'mt-1.5', tone: OUTCOME_TONE[repair.outcome] || 'muted' }),
      jsxs('div', {
        className: 'min-w-0 flex-1',
        children: [
          jsxs('div', {
            className: 'flex items-baseline gap-1.5',
            children: [
              jsx('span', {
                className: 'truncate text-xs text-(--ui-text-primary)',
                title: repair.job_id,
                children: jobLabel(repair.job_name, repair.job_id)
              }),
              repair.demo
                ? jsx(Badge, {
                    className: 'shrink-0 text-[0.625rem] uppercase',
                    title: 'A demo: Watchdog created this job, broke it and deleted it',
                    variant: 'secondary',
                    children: 'demo'
                  })
                : null,
              jsx('span', {
                className: 'shrink-0 text-[0.6875rem] text-(--ui-text-quaternary)',
                title: absolute(repair.started_at),
                children: relative(repair.started_at)
              })
            ]
          }),
          jsx('div', {
            className: 'mt-0.5 truncate text-[0.6875rem] text-(--ui-text-tertiary)',
            children: (PLAIN_OUTCOME[repair.outcome] || repair.outcome)
              + (repair.attempts > 1 ? ' · ' + repair.attempts + ' attempts' : '')
          }),
          // The proof, not a promise: what Hermes's own record says happened.
          // This is the whole product, so it gets its own line instead of a tooltip.
          tidyDetail(repair)
            ? jsx('div', {
                className: 'mt-0.5 truncate text-[0.6875rem] text-(--ui-text-quaternary)',
                title: tidyDetail(repair),
                children: tidyDetail(repair)
              })
            : null
        ]
      })
    ]
  })
}

/** A feed invites double-counting: group per job, newest outcome first. */
function byJob(repairs) {
  const groups = new Map()
  for (const repair of repairs) {
    const key = repair.job_id || repair.incident_id
    const group = groups.get(key)
    if (!group) {
      groups.set(key, { ...repair, attempts: 1 })
      continue
    }
    group.attempts += 1
  }
  return Array.from(groups.values()).sort((a, b) => (b.started_at || 0) - (a.started_at || 0))
}

function SectionLabel({ children }) {
  return jsx('div', {
    className: 'px-3 pt-3 pb-1 text-[0.625rem] font-medium tracking-wide text-(--ui-text-quaternary) uppercase',
    children
  })
}

/** Shared body: the docked pane renders it compact, the sidebar page renders it full width. */
function WatchdogBody({ ctx, compact }) {
  const client = useQueryClient()
  const { data, error, isFetching, refetch } = useWatchdog(ctx)

  const run = async (jobId, dryRun) => {
    if (!ctx || !ctx.rest) {
      return
    }

    const report = await ctx
      .rest('/repair', { body: { dry_run: Boolean(dryRun), job_id: jobId || null }, method: 'POST' })
      .catch(thrown => ({ error: String(thrown) }))

    if (report && report.error) {
      host.notify({ kind: 'error', message: 'Hermes Watchdog repair failed: ' + report.error })

      return
    }

    const attempts = (report && report.attempts) || []
    const fixed = (report && report.repaired && report.repaired.length) || 0
    const failed = (report && report.failed && report.failed.length) || 0
    const escalated = (report && report.escalated && report.escalated.length) || 0
    const skipped = (report && report.skipped && report.skipped.length) || 0
    const stale = (report && report.stale && report.stale.length) || 0
    const staleClosed = ((report && report.stale) || []).filter(item => item.closed).length

    let message
    if (dryRun) {
      // A plan has to distinguish "nothing to do" from "nothing I can fix".
      const repairs = attempts.filter(a => !(a.steps || []).includes('escalate')).length
      const handoffs = attempts.filter(a => (a.steps || []).includes('escalate')).length + skipped
      message = attempts.length + skipped === 0
        ? 'Nothing to fix — every scheduled job ran clean'
        : 'If you press Fix now: ' + repairs + ' would be fixed, ' + handoffs + ' would stay with you'
    } else if (fixed + failed + escalated + skipped + stale === 0) {
      message = 'Nothing to fix — every scheduled job ran clean'
    } else {
      // A skipped incident is only 'skipped' because today's attempts are spent —
      // that is a hand-off, never silence.
      const lists = ((report && report.escalated) || []).concat((report && report.skipped) || [])
      const unrecorded = lists.filter(item => item.handed_over === false).length
      message = 'Hermes Watchdog: ' + fixed + ' fixed'
        + (escalated + skipped ? ' · ' + (escalated + skipped) + ' still need you' : '')
        + (staleClosed ? ' · ' + staleClosed + ' tidied away' : '')
        + (failed ? ' · ' + failed + ' could not be fixed' : '')
        + (unrecorded ? ' · handoff not recorded in Hermes (cron store refused)' : '')
    }

    host.notify({ kind: failed > 0 ? 'warning' : 'success', message })
    setOutcome({
      at: Date.now(),
      text: message,
      tone: failed > 0 || escalated + skipped > 0 ? 'warn' : 'good',
      next: fixed + failed + escalated + skipped + stale === 0
        ? 'Nothing else to do.'
        : (escalated + skipped > 0
            ? 'The rows below say what broke, what was tried and what to do about each one.'
            : 'Everything it tried, it could prove worked.')
    })
    client.invalidateQueries({ queryKey: KEY })
  }

  // A fresh install has an empty repair list, so the pane proves nothing. This runs
  // the real loop on a real throwaway job and reports what Hermes recorded.
  const [demoBusy, setDemoBusy] = useState(false)
  // A toast disappears; the answer to "what now?" has to stay on the page.
  const [outcome, setOutcome] = useState(null)
  const runDemo = async () => {
    if (!ctx || !ctx.rest || demoBusy) {
      return
    }
    setDemoBusy(true)
    const result = await ctx.rest('/demo', { method: 'POST' }).catch(thrown => ({ error: String(thrown) }))
    setDemoBusy(false)
    if (result && result.error) {
      host.notify({ kind: 'error', message: 'The demo could not run: ' + result.error })
    } else if (result && result.ok) {
      host.notify({
        kind: 'success',
        message: 'Watchdog fixed a job it broke on purpose: ' + (result.detail || 'verified by Hermes')
      })
      setOutcome({
        at: Date.now(),
        text: 'Demo: created a throwaway job, broke it, repaired it, checked Hermes\'s own run record, deleted it — '
          + (result.detail || 'verified by Hermes'),
        tone: 'good',
        next: 'Your own jobs were not touched. That is the whole loop a real incident goes through.'
      })
    } else {
      host.notify({
        kind: 'warning',
        message: 'The demo repair did not verify: ' + ((result && result.detail) || 'no reason returned')
      })
      setOutcome({
        at: Date.now(),
        text: 'Demo repair did not verify: ' + ((result && result.detail) || 'no reason returned'),
        tone: 'warn',
        next: 'That is the honest case — Watchdog reports it instead of claiming a fix.'
      })
    }
    client.invalidateQueries({ queryKey: KEY })
  }

  const ack = async incidentId => {
    if (!ctx || !ctx.rest) {
      return
    }

    const result = await ctx
      .rest('/ack', { body: { incident_id: incidentId }, method: 'POST' })
      .catch(thrown => ({ error: String(thrown) }))

    setOutcome(result && result.closed
      ? { at: Date.now(), text: 'Marked done — the row is gone and stays quiet unless the same error returns',
          tone: 'good', next: 'Nothing else to do for it.' }
      : { at: Date.now(), text: 'Could not close it: ' + ((result && result.reason) || 'no reason returned'),
          tone: 'warn', next: 'The row stays open so the failure is not lost.' })

    host.notify({
      kind: result && result.closed ? 'success' : 'warning',
      message: result && result.closed
        ? 'Hidden — you will only hear about it if this happens again'
        : (result && result.error && String(result.error).includes('404')
            ? 'This plugin build is not loaded in the gateway yet — restart the gateway (hermes gateway restart), then reload'
            : 'Could not close it: ' + ((result && result.reason) || 'no reason returned (restart the gateway so the new route loads)'))
    })
    client.invalidateQueries({ queryKey: KEY })
  }

  if (!data && !error) {
    return jsx('div', {
      className: 'px-3 py-3 text-xs text-(--ui-text-tertiary)',
      children: 'Checking your scheduled jobs…'
    })
  }

  if (error) {
    return jsxs('div', {
      className: 'p-4 text-xs text-(--ui-text-tertiary)',
      children: [
        'Watchdog backend unreachable. The plugin is enabled but its API router is not mounted on this gateway.',
        jsx('div', {
          className: 'mt-2 text-(--ui-text-quaternary)',
          children: 'Restart the gateway (or Hermes Desktop) after installing, then reload this page.'
        })
      ]
    })
  }

  if (!data) {
    return jsx('div', {
      className: 'flex h-full min-h-40 items-center justify-center',
      children: jsx(GlyphSpinner, {})
    })
  }

  const health = data.health || 'unknown'
  const incidents = data.incidents || []
  const repairs = data.recent_repairs || []
  const summary = data.repairs || {}
  const counts = data.counts || {}

  return jsxs('div', {
    className: 'flex h-full min-h-0 flex-col',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 border-b border-(--ui-stroke-secondary) px-3 py-2',
        children: [
          jsx(StatusDot, { tone: TONE[health] || 'muted' }),
          jsx('span', {
            className: 'text-xs font-medium text-(--ui-text-primary)',
            children: HEALTH_LABEL[health] || health
          }),
          jsx('span', {
            className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
            children: (counts.jobs === 0
              ? 'no jobs yet'
              : incidents.length === 0
                ? (counts.jobs || 0) + ' jobs watched'
                : incidents.length + (incidents.length === 1 ? ' needs you' : ' need you')
                  + ' · ' + (counts.jobs || 0) + ' jobs watched')
              + (data.last_cycle && !data.last_cycle.dry_run
                ? ' · ' + checked(data.last_cycle.checked_at)
                : '')
          }),
          jsx('span', { className: 'flex-1' }),
          jsx(Button, {
            disabled: isFetching,
            onClick: () => refetch(),
            size: 'icon-xs',
            variant: 'ghost',
            children: jsx(Codicon, { name: 'refresh' })
          })
        ]
      }),
      jsxs('div', {
        className: 'flex items-center gap-1.5 px-3 py-2',
        children: [
          jsx(Button, { onClick: () => run(null, false), size: 'xs', variant: 'default', children: 'Check everything now' }),
          jsx(Button, {
            disabled: demoBusy,
            onClick: runDemo,
            size: 'xs',
            variant: 'secondary',
            title: 'Creates a job, breaks it, fixes it and deletes it — all on this machine',
            children: demoBusy ? 'Running the demo…' : 'Show me a fix'
          }),
          jsx('span', {
            className: 'self-center text-[0.6875rem] text-(--ui-text-quaternary)',
            children: repairs.length === 0
              ? 'Or watch one on a job Watchdog breaks on purpose.'
              : 'Runs a check and fixes whatever it can.'
          })
        ]
      }),
      outcome
        ? jsxs('div', {
            'aria-live': 'polite',
            role: 'status',
            className: cn('mx-3 mb-2 rounded border px-2 py-1.5 text-xs leading-5',
              outcome.tone === 'good'
                ? 'border-(--ui-stroke-secondary)/60 text-(--ui-text-secondary)'
                : 'border-(--ui-text-warning)/40 text-(--ui-text-secondary)'),
            children: [
              jsx('div', { children: outcome.text }),
              outcome.next
                ? jsx('div', { className: 'mt-0.5 text-[0.6875rem] text-(--ui-text-tertiary)', children: outcome.next })
                : null
            ]
          })
        : null,
      jsx(ScrollArea, {
        className: 'min-h-0 flex-1',
        children: jsxs('div', {
          children: [
            (counts.jobs || 0) === 0 && incidents.length === 0
              ? jsxs('div', {
                  className: 'px-3 pt-3 pb-1',
                  children: [
                    jsx(EmptyState, { title: 'No scheduled jobs yet' }),
                    jsx('div', {
                      className: 'mt-1 text-xs text-(--ui-text-tertiary)',
                      children: 'Create a cron job and Watchdog starts watching it: it runs the repair that matches the failure, then checks Hermes\'s own record to see whether the next run worked.'
                    })
                  ]
                })
              : null,
            incidents.length === 0
              ? null
              : jsx(SectionLabel, { children: incidents.length === 1 ? '1 job needs you' : incidents.length + ' jobs need you' }),
            incidents.map(incident =>
                  jsx(IncidentRow, {
                    busy: isFetching,
                    compact,
                    incident,
                    key: incident.incident_id,
                    onAck: ack,
                    onRepair: jobId => run(jobId, false)
                  })
                ),
            jsx(SectionLabel, { children: 'Recent repairs' }),
            repairs.length === 0
              ? jsx('div', {
                  className: 'px-3 pb-3 text-[0.6875rem] text-(--ui-text-tertiary)',
                  children: 'No repair attempts recorded yet.'
                })
              : byJob(repairs).map(group =>
                  jsx(RepairRow, { compact, key: group.job_id + '-' + group.started_at, repair: group })
                ),
            data.upstream && data.upstream.ok === false
              ? jsx('div', {
                  className: 'px-3 py-2 text-[0.6875rem] text-(--ui-text-quaternary)',
                  children: 'Upstream unavailable: ' + ((data.upstream.errors || []).join('; '))
                })
              : null
          ]
        })
      })
    ]
  })
}

/** Three numbered steps: what happens, and why it matters. */
function HowItWorks() {
  const steps = [
    ['1', 'It checks every scheduled job after it runs.'],
    ['2', 'A job that fails gets the matching fix, and only counts as fixed if its next run succeeds.'],
    ['3', 'You only see the jobs it could not fix.']
  ]

  return jsxs('details', {
    className: 'mx-6 mb-3 rounded-md border border-(--ui-stroke-secondary)/60 bg-(--ui-bg-secondary)/40 px-4 py-2.5',
    children: [
      jsx('summary', {
        className: 'cursor-pointer text-[0.6875rem] font-medium tracking-wide text-(--ui-text-tertiary) uppercase',
        children: 'How this works'
      }),
      jsxs('div', {
        className: 'mt-2 grid gap-2',
        children: [
        ...steps.map(([n, what]) => jsxs('div', {
          className: 'flex items-center gap-2.5',
          children: [
            jsx('div', {
              className: 'flex h-5 w-5 shrink-0 items-center justify-center rounded-full border border-(--ui-stroke-secondary) text-[0.6875rem] text-(--ui-text-secondary)',
              children: n
            }),
            jsx('div', { className: 'text-xs text-(--ui-text-primary)', children: what })
          ]
        }, `step-${n}`))
        ]
      })
    ]
  })
}

/** The sidebar page — full width, same report, works on every layout. */
function WatchdogPage({ ctx }) {
  return jsxs('div', {
    className: 'flex h-full min-h-0 flex-col',
    children: [
      jsxs('div', {
        className: 'flex items-baseline gap-2 px-6 pt-5 pb-3',
        children: [
          jsx('div', { className: 'text-sm font-semibold text-(--ui-text-primary)', children: 'Hermes Watchdog' }),
          jsx('div', {
            className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
            children: 'cron jobs that fix themselves · repairs verified against Hermes’s own run record'
          })
        ]
      }),
      jsx(HowItWorks, {}),
      jsx('div', {
        className: 'mx-6 mb-4 min-h-0 flex-1 overflow-hidden rounded-md border border-(--ui-stroke-secondary)',
        children: jsx(WatchdogBody, { compact: false, ctx })
      })
    ]
  })
}

export default {
  id: 'hermes-watchdog',
  name: 'Hermes Watchdog',
  register(ctx) {
    ctx.register({
      area: 'statusBar.right',
      id: 'watchdog-chip',
      order: 120,
      render: () => jsx(Chip, { ctx })
    })

    ctx.register({
      area: 'panes',
      data: {
        dock: { pane: 'workspace', pos: 'right' },
        minWidth: '260px',
        placement: 'right',
        width: '320px'
      },
      id: 'watchdog',
      render: () =>
        jsx('div', {
          className: 'flex h-full min-h-0 flex-col',
          children: jsx(WatchdogBody, { compact: true, ctx })
        }),
      title: 'Hermes Watchdog'
    })

    ctx.register({
      area: ROUTES_AREA,
      data: { path: PAGE_PATH },
      id: 'watchdog-page',
      render: () => jsx(WatchdogPage, { ctx }),
      title: 'Hermes Watchdog'
    })

    ctx.register({
      area: SIDEBAR_NAV_AREA,
      data: { codicon: 'pulse', label: 'Watchdog', path: PAGE_PATH },
      id: 'watchdog-nav'
    })
  }
}
