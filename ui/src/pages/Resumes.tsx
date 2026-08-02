/** Tailored Resumes — every resume JobPilot has rewritten for a specific job. */
import clsx from 'clsx'
import {
  AlertTriangle,
  Copy,
  Download,
  FileText,
  Trash2,
  TrendingUp,
} from 'lucide-react'
import { useState } from 'react'

import { PageHeader } from '@/components/layout/PageHeader'
import { HelpTip, PageHelp } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import {
  Card,
  Chip,
  Dialog,
  EmptyState,
  SkeletonRows,
} from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { formatUsd, relativeTime } from '@/lib/format'
import { useDeleteTailored, useTailored, useTailoredDetail } from '@/lib/tailored'
import type { TailoredResume } from '@/lib/tailored'

function AtsDelta({ before, after }: { before: number | null; after: number | null }) {
  if (after == null) return null
  const delta = before == null ? null : Math.round(after - before)
  return (
    <span className="flex items-center gap-1.5 text-xs">
      <TrendingUp className="h-3 w-3 text-faint" />
      <span className="text-muted">
        ATS {before != null ? `${Math.round(before)} → ` : ''}
        <span className="font-medium text-ink">{Math.round(after)}</span>
      </span>
      {delta != null && delta !== 0 && (
        <Chip tone={delta > 0 ? 'ok' : 'warn'}>
          {delta > 0 ? '+' : ''}
          {delta}
        </Chip>
      )}
    </span>
  )
}

function DetailDialog({ id, onClose }: { id: number | null; onClose: () => void }) {
  const { data, isLoading } = useTailoredDetail(id)
  const toast = useToast()

  const copyTex = async () => {
    if (!data) return
    try {
      const res = await fetch(`/api/tailored/${data.id}/download/tex`)
      const text = await res.text()
      await navigator.clipboard.writeText(text)
      toast.success('LaTeX copied — paste it into a new Overleaf project.')
    } catch {
      toast.error('Could not copy. Use the download button instead.')
    }
  }

  return (
    <Dialog
      open={id != null}
      onClose={onClose}
      size="lg"
      title={data ? data.role || 'Tailored resume' : 'Tailored resume'}
      subtitle={data ? `${data.company} · ${data.folder_name}` : undefined}
      footer={
        data && (
          <>
            {data.has_tex && (
              <button type="button" className="btn-secondary btn-sm" onClick={copyTex}>
                <Copy className="h-3.5 w-3.5" />
                Copy for Overleaf
                <HelpTip id="resume.overleaf" />
              </button>
            )}
            {data.has_pdf && (
              <a
                href={`/api/tailored/${data.id}/download/pdf`}
                className="btn-primary btn-sm"
              >
                <Download className="h-3.5 w-3.5" />
                Download PDF
              </a>
            )}
          </>
        )
      }
    >
      {isLoading && <SkeletonRows rows={4} />}
      {data && (
        <>
          <p className="mb-4 flex items-start gap-2 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">
            <AlertTriangle className="mt-0.5 h-3.5 w-3.5 shrink-0" />
            Always read a tailored resume before sending it. Automated tailoring can shift
            spacing and page breaks.
          </p>

          <div className="mb-5 flex flex-wrap items-center gap-4">
            <AtsDelta before={data.ats_before} after={data.ats_after} />
            {data.cost_usd > 0 && (
              <span className="text-xs text-muted">{formatUsd(data.cost_usd)}</span>
            )}
            <Chip tone={data.status === 'done' ? 'ok' : 'warn'}>{data.status}</Chip>
          </div>

          {data.validation && !data.validation.ok && (
            <div className="mb-4 rounded-lg bg-danger/10 px-3 py-2 text-xs text-danger">
              <p className="font-medium">This document has problems:</p>
              <ul className="mt-1 list-disc pl-4">
                {data.validation.problems.map((p) => (
                  <li key={p}>{p}</li>
                ))}
              </ul>
            </div>
          )}
          {data.validation?.warnings?.length ? (
            <div className="mb-4 rounded-lg bg-warn/10 px-3 py-2 text-xs text-warn">
              {data.validation.warnings.map((w) => (
                <p key={w}>{w}</p>
              ))}
            </div>
          ) : null}

          {data.has_pdf ? (
            <object
              data={`/api/tailored/${data.id}/download/pdf`}
              type="application/pdf"
              className="h-[46vh] w-full rounded-lg border border-line"
            >
              <p className="p-4 text-sm text-muted">
                Your browser can't preview PDFs inline — use the download button.
              </p>
            </object>
          ) : (
            <p className="rounded-lg bg-raised px-3 py-2 text-sm text-muted">
              {data.message ||
                'No PDF was produced. The LaTeX source is ready — paste it into Overleaf.'}
            </p>
          )}

          {data.files?.length ? (
            <ul className="mt-4 space-y-1 text-xs text-muted">
              {data.files.map((f) => (
                <li key={f.name} className="flex items-center gap-2">
                  <FileText className="h-3 w-3 text-faint" />
                  {f.name}
                  <span className="text-faint">{Math.round(f.size / 1024)} KB</span>
                </li>
              ))}
            </ul>
          ) : null}
        </>
      )}
    </Dialog>
  )
}

export function ResumesPage() {
  const { data, isLoading } = useTailored()
  const remove = useDeleteTailored()
  const [open, setOpen] = useState<number | null>(null)
  const toast = useToast()

  return (
    <>
      <PageHeader
        title="Tailored Resumes"
        description="Resumes JobPilot has rewritten for a specific job."
      >
        <PageHelp title="How tailoring works">
          <p>
            Tailoring reorders and re-emphasises what your resume already says, aimed at
            one job description. It <strong>never</strong> invents experience, employers
            or dates.
          </p>
          <p>
            Every resume is written as an ATS-safe LaTeX document — single column, no
            tables or images, standard section names — because that's what survives
            automated parsing. You get the PDF and the source; the source compiles
            unchanged on Overleaf if you want to adjust the wording.
          </p>
        </PageHelp>
      </PageHeader>

      {data && !data.tectonic && (
        <Card className="mb-5 border-warn/40">
          <p className="text-sm text-muted">
            <span className="font-medium text-ink">No PDF compiler installed.</span>{' '}
            JobPilot will still produce the LaTeX source for every tailored resume — install{' '}
            <code className="rounded bg-raised px-1">tectonic</code> to get PDFs directly,
            or paste the source into Overleaf.
          </p>
        </Card>
      )}

      <Card
        title="Library"
        subtitle={data ? `${data.count} tailored resume${data.count === 1 ? '' : 's'}` : undefined}
        bodyClassName="p-0"
      >
        {isLoading ? (
          <div className="p-4">
            <SkeletonRows rows={4} />
          </div>
        ) : !data?.items.length ? (
          <EmptyState
            icon={<FileText className="h-5 w-5" />}
            title="No tailored resumes yet"
            description="Open any job from Home and choose “Tailor resume”. It takes about a minute."
          />
        ) : (
          <ul>
            {data.items.map((item: TailoredResume) => (
              <li
                key={item.id}
                className="flex flex-wrap items-center gap-3 border-t border-line px-5 py-3.5 first:border-t-0"
              >
                <FileText
                  className={clsx(
                    'h-4 w-4 shrink-0',
                    item.has_pdf ? 'text-accent' : 'text-faint',
                  )}
                />
                <button
                  type="button"
                  className="min-w-0 flex-1 text-left"
                  onClick={() => setOpen(item.id)}
                >
                  <p className="truncate text-sm font-medium text-ink">
                    {item.role || item.folder_name}
                  </p>
                  <p className="truncate text-xs text-muted">
                    {item.company} · {relativeTime(item.created_at)}
                    {!item.has_pdf ? ' · source only' : ''}
                  </p>
                </button>

                <AtsDelta before={item.ats_before} after={item.ats_after} />

                <div className="flex shrink-0 items-center gap-1">
                  {item.has_pdf && (
                    <a
                      href={`/api/tailored/${item.id}/download/pdf`}
                      className="btn-icon"
                      title="Download PDF"
                      onClick={(e) => e.stopPropagation()}
                    >
                      <Download className="h-3.5 w-3.5" />
                    </a>
                  )}
                  <button
                    type="button"
                    className="btn-icon hover:text-danger"
                    title="Delete"
                    onClick={async () => {
                      if (!window.confirm(`Delete the tailored resume for ${item.company}?`))
                        return
                      try {
                        await remove.mutateAsync(item.id)
                        toast.info('Deleted.')
                      } catch (e) {
                        toast.error(e instanceof ApiError ? e.detail : 'Could not delete that.')
                      }
                    }}
                  >
                    <Trash2 className="h-3.5 w-3.5" />
                  </button>
                </div>
              </li>
            ))}
          </ul>
        )}
      </Card>

      <DetailDialog id={open} onClose={() => setOpen(null)} />
    </>
  )
}
