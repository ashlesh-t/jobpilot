/** A harness-style editor for the pipeline: every phase as a node in its dependency
 *  chain, laid out on a dotted canvas. Click a node to inspect and configure it — its
 *  title, description, an on/off toggle (optional phases only), and which model runs
 *  it (agent phases only, options dynamic per active engine — Claude and Gemini name
 *  their models differently). Save persists server-side, so it becomes the default for
 *  every hunt from here on, whether started from the UI or the scheduler, until it's
 *  edited again. Required phases can't be turned off — skipping them breaks whatever
 *  depends on their output. */
import clsx from 'clsx'
import { ChevronRight, Pencil, RotateCcw } from 'lucide-react'
import { useEffect, useMemo, useState } from 'react'

import { useToast } from '@/components/ui/Toast'
import { Chip, Dialog, Field, Toggle } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import {
  useConfig,
  useModels,
  usePhaseCatalog,
  usePipelineConfig,
  useSavePipelineConfig,
} from '@/lib/hooks'
import type { ModelOption, PhaseConfig, PhaseInfo } from '@/lib/hooks'

const TIER_LABEL: Record<string, string> = { fast: 'Fast', reasoning: 'Reasoning' }

function Node({
  phase,
  cfg,
  selected,
  editable,
  onClick,
}: {
  phase: PhaseInfo
  cfg: PhaseConfig
  selected: boolean
  editable: boolean
  onClick: () => void
}) {
  const on = cfg.enabled
  return (
    <button
      type="button"
      onClick={onClick}
      title={phase.help}
      className={clsx(
        'flex h-16 w-36 shrink-0 flex-col items-start justify-center gap-1 rounded-lg border px-3 py-2 text-left transition-colors',
        on ? 'border-accent/50 bg-accent-soft' : 'border-line bg-raised opacity-50',
        editable && selected && 'ring-2 ring-accent ring-offset-1 ring-offset-surface',
        editable ? 'cursor-pointer hover:border-accent/60' : 'cursor-default',
      )}
    >
      <span className="flex w-full min-w-0 items-center gap-1 text-xs font-medium text-ink">
        <span className="truncate">{phase.label}</span>
      </span>
      <span className="truncate text-[10px] uppercase tracking-wide text-faint">
        {phase.kind === 'llm' ? 'agent step' : 'script'}
        {!phase.optional && ' · required'}
      </span>
    </button>
  )
}

/** The chain of nodes — used both inside the editor and as the read-only preview. */
function Chain({
  phases,
  config,
  editable,
  selectedKey,
  onSelect,
}: {
  phases: PhaseInfo[]
  config: Record<string, PhaseConfig>
  editable: boolean
  selectedKey?: string | null
  onSelect?: (key: string) => void
}) {
  return (
    <div
      className={clsx(
        'overflow-x-auto rounded-xl p-3',
        editable && 'wai-canvas-dots border border-line',
      )}
    >
      <div className="flex items-center">
        {phases.map((phase, i) => (
          <div key={phase.key} className="flex items-center">
            {i > 0 && <ChevronRight className="mx-0.5 h-4 w-4 shrink-0 text-faint" />}
            <Node
              phase={phase}
              cfg={config[phase.key] ?? { enabled: true, model: null }}
              selected={selectedKey === phase.key}
              editable={editable}
              onClick={() => onSelect?.(phase.key)}
            />
          </div>
        ))}
      </div>
    </div>
  )
}

/** The inspector for whichever node is selected: title, description, toggle, model. */
function Inspector({
  phase,
  cfg,
  models,
  onChange,
}: {
  phase: PhaseInfo
  cfg: PhaseConfig
  models: ModelOption[]
  onChange: (next: PhaseConfig) => void
}) {
  const preferredId = useMemo(
    () => models.find((m) => m.tier === phase.model_tier)?.id,
    [models, phase.model_tier],
  )

  return (
    <div className="rounded-xl border border-line bg-surface p-4">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <h4 className="text-sm font-semibold text-ink">{phase.label}</h4>
          <p className="mt-1 text-xs text-muted">{phase.help}</p>
        </div>
        {phase.optional ? (
          <Toggle
            checked={cfg.enabled}
            onChange={(enabled) => onChange({ ...cfg, enabled })}
            label="Run this step"
          />
        ) : (
          <Chip tone="neutral">Required</Chip>
        )}
      </div>

      {phase.kind === 'llm' && (
        <div className="mt-3">
          <Field
            label="Model"
            hint={
              phase.model_locked
                ? `Always runs on the ${TIER_LABEL[phase.model_tier ?? ''] ?? ''} tier — a ${phase.label.toLowerCase()} lookup doesn't need a heavier model, so this isn't configurable.`
                : undefined
            }
          >
            <select
              className="input"
              disabled={phase.model_locked || !models.length}
              value={phase.model_locked ? (preferredId ?? '') : cfg.model ?? ''}
              onChange={(e) => onChange({ ...cfg, model: e.target.value || null })}
            >
              {!phase.model_locked && <option value="">Default for this step</option>}
              {models.map((m) => (
                <option key={m.id} value={m.id}>
                  {m.label}
                  {m.id === preferredId ? ' (Preferred)' : ''}
                </option>
              ))}
            </select>
          </Field>
        </div>
      )}
    </div>
  )
}

/** Opens the full pipeline editor and saves the choices server-side. */
function PipelineEditorDialog({
  open,
  onClose,
  phases,
  saved,
  engine,
}: {
  open: boolean
  onClose: () => void
  phases: PhaseInfo[]
  saved: Record<string, PhaseConfig>
  engine: string | undefined
}) {
  const [draft, setDraft] = useState<Record<string, PhaseConfig>>(saved)
  const [selectedKey, setSelectedKey] = useState<string | null>(null)
  const save = useSavePipelineConfig()
  const toast = useToast()
  const models = useModels(engine)

  useEffect(() => {
    if (open) {
      setDraft(saved)
      setSelectedKey(phases[0]?.key ?? null)
    }
  }, [open]) // eslint-disable-line react-hooks/exhaustive-deps

  const onSave = async () => {
    try {
      await save.mutateAsync(draft)
      toast.success('Pipeline saved — every hunt from here uses this until you change it.')
      onClose()
    } catch (error) {
      toast.error(error instanceof ApiError ? error.detail : 'Could not save the pipeline.')
    }
  }

  const resetAll = () => {
    setDraft(Object.fromEntries(phases.map((p) => [p.key, { enabled: true, model: null }])))
  }

  const selected = phases.find((p) => p.key === selectedKey)

  return (
    <Dialog
      open={open}
      onClose={onClose}
      size="lg"
      title="Edit pipeline"
      subtitle="Click a step to configure it, then save."
      footer={
        <>
          <button type="button" className="btn-ghost btn-sm" onClick={resetAll}>
            <RotateCcw className="h-3.5 w-3.5" />
            Reset to defaults
          </button>
          <button type="button" className="btn-secondary btn-sm" onClick={onClose}>
            Cancel
          </button>
          <button
            type="button"
            className="btn-primary btn-sm"
            onClick={onSave}
            disabled={save.isPending}
          >
            {save.isPending ? 'Saving…' : 'Save'}
          </button>
        </>
      }
    >
      <Chain
        phases={phases}
        config={draft}
        editable
        selectedKey={selectedKey}
        onSelect={setSelectedKey}
      />

      {selected && (
        <div className="mt-4">
          <Inspector
            phase={selected}
            cfg={draft[selected.key] ?? { enabled: true, model: null }}
            models={models.data ?? []}
            onChange={(next) => setDraft((d) => ({ ...d, [selected.key]: next }))}
          />
        </div>
      )}

      <p className="mt-3 text-xs text-faint">
        Required steps always run — skipping them would break whatever depends on their
        output. Optional steps can be turned off to make hunts faster or cheaper, and
        every agent step can run on a different model: fast (Haiku-class) for
        search-heavy work, reasoning (Sonnet-class) for judgment calls. Opus-tier models
        are never picked by default — choose one explicitly here if you want it.
      </p>
    </Dialog>
  )
}

/** The Job Hunt entry point: a compact read-only preview of the saved pipeline, with
 *  an Edit button that opens the full canvas. */
export function PipelineCanvas({
  onSelectionChange,
}: {
  /** Called whenever the saved selection is known/changes, so the caller can pass it
   *  as `only` when starting a run. */
  onSelectionChange: (keys: string[] | null) => void
}) {
  const catalog = usePhaseCatalog()
  const pipeline = usePipelineConfig()
  const config = useConfig()
  const [editing, setEditing] = useState(false)

  const phases = catalog.data ?? []
  const engine = (config.data as { engine?: { provider?: string } } | undefined)?.engine
    ?.provider
  const saved = useMemo(() => {
    const fromServer = pipeline.data
    if (fromServer) return fromServer
    return Object.fromEntries(phases.map((p) => [p.key, { enabled: true, model: null }]))
  }, [pipeline.data, phases])

  useEffect(() => {
    if (!phases.length) return
    const anyCustomized = phases.some((p) => saved[p.key] && !saved[p.key].enabled)
    onSelectionChange(
      anyCustomized ? phases.filter((p) => saved[p.key]?.enabled ?? true).map((p) => p.key) : null,
    )
  }, [phases, saved, onSelectionChange])

  if (!phases.length) return null

  const isCustomized = phases.some((p) => saved[p.key] && !saved[p.key].enabled)

  return (
    <div>
      <div className="mb-2 flex items-center justify-between">
        <span className="label inline-flex">
          Pipeline
          {isCustomized && <Chip tone="accent">Customized</Chip>}
        </span>
        <button
          type="button"
          className="btn-secondary btn-sm"
          onClick={() => setEditing(true)}
        >
          <Pencil className="h-3.5 w-3.5" />
          Edit pipeline
        </button>
      </div>
      <Chain phases={phases} config={saved} editable={false} />
      <PipelineEditorDialog
        open={editing}
        onClose={() => setEditing(false)}
        phases={phases}
        saved={saved}
        engine={engine}
      />
    </div>
  )
}
