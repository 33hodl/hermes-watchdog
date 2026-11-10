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
import { jsx, jsxs } from 'react/jsx-runtime'

const ROUTES_AREA = 'routes'
const SIDEBAR_NAV_AREA = 'sidebar.nav'
const PAGE_PATH = '/watchdog'

const TONE = { ok: 'good', degraded: 'warn', critical: 'bad', unknown: 'muted' }
const HEALTH_LABEL = { ok: 'healthy', degraded: 'degraded', critical: 'critical', unknown: 'no data' }
const OUTCOME_TONE = { repaired: 'good', failed: 'bad', escalated: 'warn', running: 'muted' }

const POLL_MS = 15000
const KEY = ['hermes-watchdog', 'status']

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
  return jsxs('button', {
    className: cn('inline-flex h-full cursor-pointer items-center gap-1 px-1.5 text-[0.6875rem]',
      'text-(--ui-text-tertiary) hover:text-(--ui-text-secondary)'),
    onClick: () => host.navigate(PAGE_PATH),
    title: 'Open Hermes Watchdog',
    type: 'button',
    children: [
      jsx(StatusDot, { tone: TONE[health] || 'muted' }),
      jsx('span', { children: incidents > 0 ? 'watchdog ' + incidents : 'watchdog' })
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
                children: incident.job_name || incident.job_id
              }),
              jsx(Badge, { variant: incident.state === 'alerted' ? 'warn' : 'muted', children: incident.failure_type }),
              incident.state === 'alerted'
                ? jsx(Badge, { variant: 'warn', children: 'needs you' })
                : null
            ]
          }),
          jsx('div', {
            className: 'mt-0.5 line-clamp-2 text-[0.6875rem] leading-4 text-(--ui-text-tertiary)',
            children: incident.error || 'no error text recorded'
          }),
          jsx('div', {
            className: 'mt-1 text-[0.6875rem] leading-4 text-(--ui-text-quaternary)',
            children: incident.state === 'alerted'
              ? 'Handed to you: check that job’s last run, then Ack. Ack keeps it quiet until the same error returns.'
              : 'Repair runs the matching fix. Nothing gets fixed? Check the job’s last run, then Ack to close it.'
          })
        ]
      }),
      jsxs('div', {
        className: 'flex shrink-0 items-center gap-1',
        children: [
          jsx(Button, {
            disabled: busy,
            onClick: () => onRepair(incident.job_id),
            size: 'xs',
            variant: 'secondary',
            children: 'Repair'
          }),
          jsx(Button, {
            disabled: busy,
            onClick: () => onAck(incident.incident_id),
            size: 'xs',
            variant: 'ghost',
            title: 'Close this incident — quiet until the same error returns',
            children: 'Ack'
          })
        ]
      })
    ]
  })
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
                children: repair.job_name || repair.job_id
              }),
              jsx('span', {
                className: 'shrink-0 text-[0.6875rem] text-(--ui-text-quaternary)',
                children: relative(repair.started_at)
              })
            ]
          }),
          jsx('div', {
            className: 'mt-0.5 truncate text-[0.6875rem] text-(--ui-text-tertiary)',
            children: repair.playbook + ' · ' + repair.outcome + (repair.detail ? ' — ' + repair.detail : '')
          })
        ]
      })
    ]
  })
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

    let message
    if (dryRun) {
      // A plan has to distinguish "nothing to do" from "nothing I can fix".
      const repairs = attempts.filter(a => !(a.steps || []).includes('escalate')).length
      const handoffs = attempts.filter(a => (a.steps || []).includes('escalate')).length + skipped
      message = attempts.length + skipped === 0
        ? 'Watchdog plan: nothing open, nothing to do'
        : 'Watchdog plan: ' + repairs + ' to repair, ' + handoffs + ' to hand to you'
    } else if (fixed + failed + escalated + skipped === 0) {
      message = 'Hermes Watchdog: nothing open, nothing to do'
    } else {
      // A skipped incident is only 'skipped' because today's attempts are spent —
      // that is a hand-off, never silence.
      const lists = ((report && report.escalated) || []).concat((report && report.skipped) || [])
      const unrecorded = lists.filter(item => item.handed_over === false).length
      message = 'Hermes Watchdog: ' + fixed + ' repaired · ' + (escalated + skipped) + ' need you'
        + (failed ? ' · ' + failed + ' failed' : '')
        + (unrecorded ? ' · handoff not recorded in Hermes (cron store refused)' : '')
    }

    host.notify({ kind: failed > 0 ? 'warning' : 'success', message })
    client.invalidateQueries({ queryKey: KEY })
  }

  const ack = async incidentId => {
    if (!ctx || !ctx.rest) {
      return
    }

    const result = await ctx
      .rest('/ack', { body: { incident_id: incidentId }, method: 'POST' })
      .catch(thrown => ({ error: String(thrown) }))

    host.notify({
      kind: result && result.closed ? 'success' : 'warning',
      message: result && result.closed
        ? 'Incident acknowledged — quiet until the same error returns'
        : 'Could not close that incident (already closed, or the cron store refused)'
    })
    client.invalidateQueries({ queryKey: KEY })
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
            children: (counts.jobs || 0) + ' jobs · ' + incidents.length + ' open'
              + (counts.needs_you ? ' · ' + counts.needs_you + ' need you' : '')
              + ' · ' + (summary.repaired_7d || 0) + ' repaired/7d'
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
          jsx(Button, { onClick: () => run(null, false), size: 'xs', variant: 'default', children: 'Run repair cycle' }),
          jsx(Button, { onClick: () => run(null, true), size: 'xs', variant: 'secondary', children: 'Plan only' })
        ]
      }),
      compact
        ? null
        : jsx('div', {
            className: 'px-3 pb-1 text-[0.6875rem] leading-4 text-(--ui-text-quaternary)',
            children: 'Green means there is nothing to do. On an open incident, Repair runs the playbook that matches the failure — and when it cannot fix the job, it pauses it and hands it to you here.'
          }),
      jsx(ScrollArea, {
        className: 'min-h-0 flex-1',
        children: jsxs('div', {
          children: [
            jsx(SectionLabel, { children: 'Open incidents' }),
            incidents.length === 0
              ? jsx(EmptyState, { description: 'Every cron job is running clean.', title: 'Nothing to fix' })
              : incidents.map(incident =>
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
              : repairs.map(repair =>
                  jsx(RepairRow, { compact, key: repair.incident_id + '-' + repair.started_at, repair })
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
