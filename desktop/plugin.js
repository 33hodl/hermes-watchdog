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
  GlyphSpinner,
  ScrollArea,
  StatusDot,
  cn,
  host,
  useQuery,
  useQueryClient
} from '@hermes/plugin-sdk'
import { useEffect, useState } from 'react'
import { jsx, jsxs } from 'react/jsx-runtime'

const BUILD = '0.9.4'
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

/** A job id is not a name a person can act on. */
function jobLabel(jobName, jobId) {
  if (jobName && jobName !== jobId) {
    return jobName
  }
  return 'A job that no longer exists'
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


/** Shared body: the docked pane renders it compact, the sidebar page renders it full width. */
function Fold({ title, children }) {
  return jsxs('details', {
    className: 'mt-3 border-t border-(--ui-stroke-secondary)/50 pt-2',
    children: [
      jsx('summary', {
        className: 'cursor-pointer select-none rounded text-xs text-(--ui-text-tertiary) hover:text-(--ui-text-secondary) focus-visible:ring-1 focus-visible:ring-(--ui-stroke-secondary) focus-visible:outline-none',
        children: title
      }),
      jsx('div', { className: 'mt-2', children })
    ]
  })
}

/** One thing that needs a person: one sentence, two buttons, nothing else. */
function IssueCard({ incident, onAsk, onAck, busy }) {
  const detail = incidentDetail(incident)
  const label = String(incident.job_name || '').toLowerCase().includes('sweep')
    ? "Watchdog's own check"
    : jobLabel(incident.job_name, incident.job_id)
  const seenAt = incident.detail && incident.detail.last_seen_at
  return jsxs('div', {
    className: 'mb-3 rounded-lg border border-(--ui-text-warning)/30 p-3',
    children: [
      jsx('div', { className: 'text-sm font-medium text-(--ui-text-primary)', children: label }),
      jsx('div', { className: 'mt-1 text-xs leading-5 text-(--ui-text-secondary)', children: detail.summary }),
      seenAt
        ? jsx('div', {
            className: 'mt-0.5 text-[0.6875rem] text-(--ui-text-quaternary)',
            title: new Date(seenAt).toLocaleString(),
            children: 'last failed ' + relative(Date.parse(seenAt) / 1000)
          })
        : null,
      jsx(RunStrip, { runs: incident.runs }),
      jsxs('div', {
        className: 'mt-2.5 flex flex-wrap items-center gap-1.5',
        children: [
          jsx(Button, {
            disabled: busy,
            onClick: () => onAsk(incident),
            size: 'xs',
            variant: 'default',
            children: busy ? 'Asking Hermes…' : 'Ask Hermes to fix it'
          }),
          jsx(Button, {
            disabled: busy,
            onClick: () => onAck(incident.incident_id),
            size: 'xs',
            variant: 'ghost',
            title: 'Hide this until the same error comes back',
            children: 'Done'
          })
        ]
      }),
      jsx(IncidentDetail, { incident })
    ]
  })
}

function WatchdogBody({ ctx, compact }) {
  const client = useQueryClient()
  const { data, error, isFetching, refetch } = useWatchdog(ctx)

  const routesProven = () => setRoutesStale(false)

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
    routesProven()
    client.invalidateQueries({ queryKey: KEY })
  }

  // A fresh install has an empty repair list, so the pane proves nothing. This runs
  // the real loop on a real throwaway job and reports what Hermes recorded.
  const [demoBusy, setDemoBusy] = useState(false)
  // A toast disappears; the answer to "what now?" has to stay on the page.
  const [outcome, setOutcome] = useState(null)
  const [busyId, setBusyId] = useState(null)
  const [routesStale, setRoutesStale] = useState(false)

  // A plugin version that adds a route needs ONE gateway restart: Hermes mounts
  // plugin API routers when it starts. Probe with an id that cannot exist, so this
  // is a no-op on a current gateway and an honest warning on a stale one.
  useEffect(() => {
    let cancelled = false
    if (!ctx || !ctx.rest) {
      return () => {}
    }
    ctx.rest('/runbooks')
      .then(() => { if (!cancelled) setRoutesStale(false) })
      .catch(thrown => {
        if (!cancelled && String(thrown).includes('404')) {
          setRoutesStale(true)
        } else if (!cancelled) {
          setRoutesStale(false)
        }
      })
    return () => { cancelled = true }
  }, [])
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

  const askHermes = async incident => {
    if (!ctx || !ctx.rest) {
      return
    }
    setBusyId(incident.incident_id)
    const result = await ctx
      .rest('/handoff', { body: { incident_id: incident.incident_id }, method: 'POST' })
      .catch(thrown => ({ ok: false, error: String(thrown) }))
    setBusyId(null)
    setOutcome(result && result.ok
      ? { at: Date.now(), tone: 'good',
          text: 'Hermes is on it — it is diagnosing that job now, and its answer arrives here as a message.',
          next: 'Nothing else is needed from you.' }
      : { at: Date.now(), tone: 'warn',
          text: String((result && result.error) || '').includes('404')
            ? 'This needs one gateway restart to load (the button is new in this version).'
            : 'Could not hand it to Hermes: ' + ((result && result.error) || 'no reason returned'),
          next: String((result && result.error) || '').includes('404')
            ? 'Run: hermes gateway restart — then press again. The issue stays open until then.'
            : 'The issue stays open, so nothing is lost.' })
    client.invalidateQueries({ queryKey: KEY })
  }

  const needsYou = incidents.length
  const headline = (counts.jobs || 0) === 0
    ? 'No scheduled jobs yet.'
    : needsYou === 0
      ? 'Everything is running as it should.'
      : needsYou === 1
        ? 'One thing needs you.'
        : needsYou + ' things need you.'
  const subline = [
    (counts.jobs || 0) === 0 ? null : (counts.jobs || 0) + ' scheduled jobs',
    data.last_cycle && !data.last_cycle.dry_run ? checked(data.last_cycle.checked_at) : null
  ].filter(Boolean).join(' · ')

  // Demo rows are noise for a person looking at their own fleet: only show them
  // when there is nothing else to show.
  const realRepairs = byJob(repairs.filter(repair => !repair.demo))

  return jsxs('div', {
    className: 'flex h-full min-h-0 flex-col',
    children: [
      jsxs('div', {
        className: 'border-b border-(--ui-stroke-secondary) px-4 pt-4 pb-3',
        children: [
          jsxs('div', {
            className: 'flex items-start gap-2',
            children: [
              jsx(StatusDot, { className: 'mt-1', tone: needsYou === 0 ? 'good' : 'warn' }),
              jsxs('div', {
                className: 'min-w-0 flex-1',
                children: [
                  jsx('div', { className: 'text-sm font-medium text-(--ui-text-primary)', children: headline }),
                  subline
                    ? jsx('div', { className: 'mt-0.5 text-xs text-(--ui-text-tertiary)', children: subline })
                    : null
                ]
              }),
              jsx(Button, {
                disabled: isFetching,
                onClick: () => run(null, false),
                size: 'icon-xs',
                variant: 'ghost',
                title: 'Check every job now — this runs the repair cycle, it does not just reload the page',
                children: jsx(Codicon, { name: isFetching ? 'sync~spin' : 'refresh' })
              })
            ]
          }),
          routesStale
            ? jsxs('div', {
                className: 'mt-2 rounded border border-(--ui-text-warning)/40 px-2 py-1.5 text-xs leading-5 text-(--ui-text-secondary)',
                children: [
                  jsx('div', { children: 'Hermes is still serving the previous version of this plugin, so the fix button cannot work yet. One restart loads it:' }),
                  jsx('button', {
                    className: 'mt-1 cursor-pointer rounded bg-(--ui-stroke-secondary)/30 px-1 py-0.5 font-mono text-[0.6875rem] text-(--ui-text-secondary) hover:text-(--ui-text-primary)',
                    onClick: () => copyCommand('hermes gateway restart'),
                    title: 'Click to copy',
                    type: 'button',
                    children: 'hermes gateway restart'
                  })
                ]
              })
            : null,
          outcome
            ? jsxs('div', {
                'aria-live': 'polite',
                role: 'status',
                className: cn('mt-2 rounded border px-2 py-1.5 text-xs leading-5',
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
            : null
        ]
      }),
      jsx(ScrollArea, {
        className: 'min-h-0 flex-1',
        children: jsxs('div', {
          className: 'px-4 py-3',
          children: [
            incidents.map(incident => jsx(IssueCard, {
              busy: busyId === incident.incident_id,
              incident,
              key: incident.incident_id,
              onAck: ack,
              onAsk: askHermes
            })),
            jsx(Fold, {
              title: 'What Watchdog does',
              children: jsxs('div', {
                className: 'space-y-1 text-xs leading-5 text-(--ui-text-tertiary)',
                children: [
                  jsx('p', { children: 'It watches every scheduled job in this profile. When one fails it tries the repair that fits — run it again, restart what broke, or pause it so it stops burning the schedule — then checks Hermes\'s own run record to see whether the next run actually worked.' }),
                  jsx('p', { children: 'It only stops to ask when a repair would be a guess: it says what broke and what you can do. Marking something done keeps it quiet until the same error comes back.' })
                ]
              })
            }),
            jsx(Fold, {
              title: realRepairs.length
                ? 'What it did recently (' + realRepairs.length + ')'
                : 'What it did recently',
              children: realRepairs.length === 0
                ? jsx('div', { className: 'text-xs text-(--ui-text-tertiary)', children: 'Nothing yet. Repairs appear here once a job fails and Watchdog handles it.' })
                : jsx('div', {
                    children: realRepairs.map(group => jsx(RepairRow, {
                      key: group.job_id + '-' + group.started_at,
                      repair: group
                    }))
                  })
            }),
            jsx(Fold, {
              title: 'See a repair happen',
              children: jsxs('div', {
                className: 'space-y-2',
                children: [
                  jsx('div', {
                    className: 'text-xs leading-5 text-(--ui-text-tertiary)',
                    children: 'Nothing broken? Watchdog will create a job, break it, repair it, check Hermes\'s own run record and delete it — a few seconds, on this machine, and your own jobs are untouched.'
                  }),
                  jsx(Button, {
                    disabled: demoBusy,
                    onClick: runDemo,
                    size: 'xs',
                    variant: 'secondary',
                    children: demoBusy ? 'Running…' : 'Run it'
                  })
                ]
              })
            }),
            data.upstream && data.upstream.ok === false
              ? jsx('div', {
                  className: 'mt-2 text-[0.6875rem] text-(--ui-text-quaternary)',
                  children: 'Hermes could not be read: ' + ((data.upstream.errors || []).join('; '))
                })
              : null,
            jsx('div', {
              className: 'mt-3 text-right text-[0.625rem] text-(--ui-text-quaternary)',
              children: 'watchdog ' + BUILD
            })
          ]
        })
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
