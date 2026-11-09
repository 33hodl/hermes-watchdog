/**
 * Watchdog — Desktop half.
 *
 * A pane and a status-bar chip over the plugin's own backend
 * (`ctx.rest` → /api/plugins/hermes-watchdog/*), which is the same engine the
 * `watchdog_status` / `watchdog_repair` tools and the on_session_end hook use.
 * Nothing here talks to Hermes internals directly.
 */

import {
  Badge,
  Button,
  Codicon,
  EmptyState,
  GlyphSpinner,
  ScrollArea,
  StatusDot,
  Tip,
  cn,
  host,
  useQuery,
  useQueryClient,
  useValue
} from '@hermes/plugin-sdk'
import { jsx, jsxs } from 'react/jsx-runtime'

const TONE = { ok: 'good', degraded: 'warn', critical: 'bad', unknown: 'muted' }
const HEALTH_LABEL = { ok: 'healthy', degraded: 'degraded', critical: 'critical', unknown: 'no data' }
const OUTCOME_TONE = { repaired: 'good', failed: 'bad', escalated: 'warn', running: 'muted' }

const POLL_MS = 15000

function relative(ts) {
  if (!ts) {
    return ''
  }

  const seconds = Math.max(0, Math.round(Date.now() / 1000 - Number(ts)))

  if (seconds < 60) {
    return `${seconds}s ago`
  }

  if (seconds < 3600) {
    return `${Math.round(seconds / 60)}m ago`
  }

  if (seconds < 86400) {
    return `${Math.round(seconds / 3600)}h ago`
  }

  return `${Math.round(seconds / 86400)}d ago`
}

function Row({ children, className }) {
  return jsx('div', {
    className: cn('flex items-start gap-2 px-3 py-2', className),
    children
  })
}

function Chip({ rest }) {
  const { data } = useQuery({
    enabled: Boolean(rest),
    queryFn: () => rest('/status'),
    queryKey: ['hermes-watchdog', 'status'],
    refetchInterval: POLL_MS,
    retry: false
  })
  const incidents = data?.counts?.open_incidents ?? 0
  const health = data?.health ?? 'unknown'

  return jsx(Tip, {
    label: `${incidents} open cron incident${incidents === 1 ? '' : 's'} · ${HEALTH_LABEL[health]}`,
    children: jsxs('span', {
      className: cn('inline-flex h-full items-center gap-1 px-1.5 text-[0.6875rem]', 'text-(--ui-text-tertiary)'),
      children: [
        jsx(StatusDot, { tone: TONE[health] ?? 'muted' }),
        jsx('span', { children: incidents > 0 ? `watchdog ${incidents}` : 'watchdog' })
      ]
    })
  })
}

function IncidentRow({ incident, onRepair, busy }) {
  return jsxs(Row, {
    className: 'border-b border-(--ui-stroke-secondary)/40 last:border-b-0',
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
              jsx(Badge, { variant: 'secondary', children: incident.failure_type })
            ]
          }),
          jsx('div', {
            className: 'mt-0.5 line-clamp-2 text-[0.6875rem] leading-4 text-(--ui-text-tertiary)',
            children: incident.error || 'no error text recorded'
          })
        ]
      }),
      jsx(Button, {
        disabled: busy,
        onClick: () => onRepair(incident.job_id),
        size: 'xs',
        variant: 'secondary',
        children: 'Repair'
      })
    ]
  })
}

function RepairRow({ repair }) {
  return jsxs(Row, {
    className: 'border-b border-(--ui-stroke-secondary)/40 last:border-b-0',
    children: [
      jsx(StatusDot, { className: 'mt-1.5', tone: OUTCOME_TONE[repair.outcome] ?? 'muted' }),
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
            children: `${repair.playbook} · ${repair.outcome}${repair.detail ? ` — ${repair.detail}` : ''}`
          })
        ]
      })
    ]
  })
}

function WatchdogPane({ ctx }) {
  const client = useQueryClient()
  const rest = ctx?.rest ? path => ctx.rest(path) : null
  const { data, error, isFetching, refetch } = useQuery({
    enabled: Boolean(rest),
    queryFn: () => rest('/status'),
    queryKey: ['hermes-watchdog', 'status'],
    refetchInterval: POLL_MS,
    retry: false
  })
  const health = data?.health ?? 'unknown'
  const incidents = data?.incidents ?? []
  const repairs = data?.recent_repairs ?? []
  const summary = data?.repairs ?? {}

  const run = async (jobId, dryRun) => {
    if (!ctx?.rest) {
      return
    }

    const report = await ctx
      .rest('/repair', { body: { dry_run: Boolean(dryRun), job_id: jobId ?? null }, method: 'POST' })
      .catch(thrown => ({ error: String(thrown) }))

    if (report?.error) {
      host.notify({ kind: 'error', message: `Hermes Watchdog repair failed: ${report.error}` })

      return
    }

    const fixed = report.repaired?.length ?? 0
    const failed = report.failed?.length ?? 0
    const escalated = report.escalated?.length ?? 0

    host.notify({
      kind: failed > 0 ? 'warning' : 'info',
      message: dryRun
        ? `Hermes Watchdog plan: ${report.attempts?.length ?? 0} incident(s) would be repaired`
        : `Hermes Watchdog: ${fixed} repaired, ${failed} failed, ${escalated} need you`
    })
    client.invalidateQueries({ queryKey: ['hermes-watchdog', 'status'] })
  }

  if (error) {
    return jsx('div', {
      className: 'p-3 text-xs text-(--ui-text-tertiary)',
      children: 'Hermes Watchdog backend unreachable. The plugin is enabled but its API router is not mounted on this gateway.'
    })
  }

  if (!data) {
    return jsx('div', {
      className: 'flex h-full items-center justify-center',
      children: jsx(GlyphSpinner, {})
    })
  }

  return jsxs('div', {
    className: 'flex h-full flex-col',
    children: [
      jsxs('div', {
        className: 'flex items-center gap-2 border-b border-(--ui-stroke-secondary) px-3 py-2',
        children: [
          jsx(StatusDot, { tone: TONE[health] ?? 'muted' }),
          jsx('span', { className: 'text-xs font-medium text-(--ui-text-primary)', children: HEALTH_LABEL[health] }),
          jsx('span', {
            className: 'text-[0.6875rem] text-(--ui-text-tertiary)',
            children: `${data.counts?.jobs ?? 0} jobs · ${incidents.length} open · ${summary.repaired_7d ?? 0} repaired/7d`
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
      jsx(ScrollArea, {
        className: 'min-h-0 flex-1',
        children: jsxs('div', {
          children: [
            jsx('div', {
              className: 'px-3 pt-1 pb-1 text-[0.625rem] font-medium tracking-wide text-(--ui-text-quaternary) uppercase',
              children: 'Open incidents'
            }),
            incidents.length === 0
              ? jsx(EmptyState, {
                  description: 'Every cron job is running clean.',
                  title: 'Nothing to fix'
                })
              : incidents.map(incident =>
                  jsx(IncidentRow, {
                    busy: isFetching,
                    incident,
                    key: incident.incident_id,
                    onRepair: jobId => run(jobId, false)
                  })
                ),
            jsx('div', {
              className: 'px-3 pt-3 pb-1 text-[0.625rem] font-medium tracking-wide text-(--ui-text-quaternary) uppercase',
              children: 'Recent repairs'
            }),
            repairs.length === 0
              ? jsx('div', {
                  className: 'px-3 pb-3 text-[0.6875rem] text-(--ui-text-tertiary)',
                  children: 'No repair attempts recorded yet.'
                })
              : repairs.map(repair =>
                  jsx(RepairRow, { key: `${repair.incident_id}-${repair.started_at}`, repair })
                ),
            data.upstream?.ok === false
              ? jsx('div', {
                  className: 'px-3 py-2 text-[0.6875rem] text-(--ui-text-quaternary)',
                  children: `Upstream unavailable: ${(data.upstream.errors || []).join('; ')}`
                })
              : null
          ]
        })
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
      render: () => jsx(Chip, { rest: ctx.rest ? path => ctx.rest(path) : null })
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
      render: () => jsx(WatchdogPane, { ctx }),
      title: 'Hermes Watchdog'
    })
  }
}
