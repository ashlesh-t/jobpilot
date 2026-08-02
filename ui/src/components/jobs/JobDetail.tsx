/** Everything JobPilot knows about one job, and why it scored the way it did. */
import { Check, ExternalLink, FileText, Undo2, Wand2 } from 'lucide-react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Chip, Dialog, ErrorState, Loading, ProgressBar } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { formatDate, formatLpa, relativeTime, scoreTone } from '@/lib/format'
import { useJob, useMarkApplied, useUnmarkApplied } from '@/lib/jobs'
import { useTailorJob } from '@/lib/tailored'

function Section({ title, helpId, children }: { title: string; helpId?: string; children: React.ReactNode }) {
  return (
    <section className="border-t border-line py-4 first:border-t-0 first:pt-0">
      <h3 className="mb-2 flex items-center gap-1.5 text-xs font-semibold uppercase tracking-wide text-muted">
        {title}
        {helpId && <HelpTip id={helpId} />}
      </h3>
      {children}
    </section>
  )
}

function SkillList({ skills, tone }: { skills: string[]; tone: 'ok' | 'warn' }) {
  if (!skills.length) return <p className="text-sm text-faint">None recorded.</p>
  return (
    <div className="flex flex-wrap gap-1.5">
      {skills.map((skill) => (
        <Chip key={skill} tone={tone}>
          {skill}
        </Chip>
      ))}
    </div>
  )
}

export function JobDetail({ jobId, onClose }: { jobId: string | null; onClose: () => void }) {
  const { data: job, isLoading, isError, error, refetch } = useJob(jobId)
  const markApplied = useMarkApplied()
  const unmark = useUnmarkApplied()
  const tailor = useTailorJob()
  const toast = useToast()

  const onTailor = async () => {
    if (!job) return
    try {
      const result = await tailor.mutateAsync(job.job_id)
      toast.success(
        result.has_pdf
          ? `Resume tailored for ${job.company} — check it on the Tailored Resumes page.`
          : `LaTeX ready for ${job.company} — ${result.message ?? 'no PDF compiler installed'}.`,
      )
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not tailor that resume.')
    }
  }

  const onApply = async () => {
    if (!job) return
    try {
      await markApplied.mutateAsync({ jobId: job.job_id })
      toast.success(`Marked applied: ${job.role} at ${job.company}`, {
        actionLabel: 'Undo',
        onAction: () => unmark.mutate(job.job_id),
      })
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not mark that applied.')
    }
  }

  return (
    <Dialog
      open={Boolean(jobId)}
      onClose={onClose}
      size="lg"
      title={job ? job.role : 'Job'}
      subtitle={
        job
          ? [job.company, job.location, job.source_board].filter(Boolean).join(' · ')
          : undefined
      }
      footer={
        job && (
          <>
            {job.application_url && (
              <a
                href={job.application_url}
                target="_blank"
                rel="noreferrer noopener"
                className="btn-secondary btn-sm"
              >
                Open posting
                <ExternalLink className="h-3.5 w-3.5" />
              </a>
            )}
            <button
              type="button"
              className="btn-secondary btn-sm"
              onClick={onTailor}
              disabled={tailor.isPending}
              title="Rewrite your resume to emphasise what this job asks for"
            >
              <Wand2 className="h-3.5 w-3.5" />
              {tailor.isPending ? 'Tailoring…' : 'Tailor resume'}
              <HelpTip id="resume.tailor" />
            </button>
            {job.application_status ? (
              <button
                type="button"
                className="btn-secondary btn-sm"
                onClick={() => {
                  unmark.mutate(job.job_id)
                  toast.info('Application removed.')
                }}
              >
                <Undo2 className="h-3.5 w-3.5" />
                Not applied after all
              </button>
            ) : (
              <button
                type="button"
                className="btn-primary btn-sm"
                onClick={onApply}
                disabled={markApplied.isPending}
              >
                <Check className="h-3.5 w-3.5" />
                Mark applied
              </button>
            )}
          </>
        )
      }
    >
      {isLoading && <Loading />}
      {isError && <ErrorState error={error} onRetry={() => refetch()} />}
      {job && (
        <>
          <Section title="Match" helpId="score.match">
            <div className="flex flex-wrap items-center gap-x-6 gap-y-3">
              <div>
                <p className="text-3xl font-semibold tabular-nums text-ink">
                  {Math.round(job.score)}
                  <span className="text-base text-faint">/100</span>
                </p>
                <p className="mt-1 text-xs text-muted">
                  {job.score_confidence === 'low' ? 'Low confidence' : 'Good confidence'}
                  {job.score_confidence === 'low' && <HelpTip id="score.confidence" />}
                </p>
              </div>
              <dl className="grid flex-1 gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
                <div className="flex items-center justify-between gap-3">
                  <dt className="flex items-center gap-1 text-muted">
                    Skills matched <HelpTip id="score.keyword" />
                  </dt>
                  <dd className="tabular-nums text-ink">{Math.round(job.keyword_score)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="flex items-center gap-1 text-muted">
                    Overall fit <HelpTip id="score.semantic" />
                  </dt>
                  <dd className="tabular-nums text-ink">{Math.round(job.semantic_score)}</dd>
                </div>
                <div className="flex items-center justify-between gap-3">
                  <dt className="flex items-center gap-1 text-muted">
                    Ranking score <HelpTip id="score.effective" />
                  </dt>
                  <dd className="tabular-nums text-ink">{Math.round(job.effective_score)}</dd>
                </div>
                {job.bar_fit !== 0 && (
                  <div className="flex items-center justify-between gap-3">
                    <dt className="flex items-center gap-1 text-muted">
                      Interview bar <HelpTip id="score.bar_fit" />
                    </dt>
                    <dd className="tabular-nums text-ink">
                      {job.bar_fit > 0 ? '+' : ''}
                      {Math.round(job.bar_fit)}
                    </dd>
                  </div>
                )}
              </dl>
            </div>
            <div className="mt-3">
              <ProgressBar value={job.score / 100} tone={scoreTone(job.score) === 'ok' ? 'ok' : 'accent'} />
            </div>
          </Section>

          <Section title="Skills you have">
            <SkillList skills={job.matched_skills} tone="ok" />
          </Section>

          {job.missing_skills.length > 0 && (
            <Section title="Skills they want that you don't list">
              <SkillList skills={job.missing_skills} tone="warn" />
            </Section>
          )}

          {(job.prep_focus || job.gap_signals) && (
            <Section title="Interview prep" helpId="score.prep_focus">
              {job.prep_focus && <p className="text-sm text-ink">{job.prep_focus}</p>}
              {job.gap_signals && (
                <p className="mt-2 text-sm text-muted">
                  <span className="font-medium text-ink">Gaps: </span>
                  {job.gap_signals}
                </p>
              )}
              {job.archetype && (
                <Chip tone="neutral" className="mt-2">
                  {job.archetype.replace(/-/g, ' ')}
                </Chip>
              )}
            </Section>
          )}

          <Section title="Money">
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-3">
              <div>
                <dt className="text-muted">Market range</dt>
                <dd className="mt-0.5 text-ink">
                  {job.market_salary ||
                    formatLpa(job.salary_min_lpa, job.salary_max_lpa, 'Not researched')}
                </dd>
              </div>
              <div>
                <dt className="text-muted">Ask for</dt>
                <dd className="mt-0.5 text-ink">{job.your_demand || '—'}</dd>
              </div>
              <div>
                <dt className="text-muted">Source</dt>
                <dd className="mt-0.5 text-ink">{job.salary_source || '—'}</dd>
              </div>
            </dl>
          </Section>

          <Section title="Timeline">
            <dl className="grid gap-x-6 gap-y-2 text-sm sm:grid-cols-2">
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Posted</dt>
                <dd className="text-ink">{job.posted_date || '—'}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Apply by</dt>
                <dd className="text-ink">{job.last_date || 'No deadline given'}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">First seen</dt>
                <dd className="text-ink">{formatDate(job.first_seen)}</dd>
              </div>
              <div className="flex justify-between gap-3">
                <dt className="text-muted">Last seen</dt>
                <dd className="text-ink">{relativeTime(job.last_seen)}</dd>
              </div>
              {job.applied_at && (
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">You applied</dt>
                  <dd className="text-ink">{formatDate(job.applied_at)}</dd>
                </div>
              )}
              {job.experience_req && (
                <div className="flex justify-between gap-3">
                  <dt className="text-muted">Experience asked</dt>
                  <dd className="text-ink">{job.experience_req}</dd>
                </div>
              )}
            </dl>
          </Section>

          {job.tailored && job.tailored.length > 0 && (
            <Section title="Tailored resumes">
              <ul className="space-y-1.5">
                {job.tailored.map((item) => (
                  <li key={item.id} className="flex items-center gap-2 text-sm">
                    <FileText className="h-3.5 w-3.5 text-faint" />
                    <span className="text-ink">{item.folder_name}</span>
                    <span className="text-faint">{relativeTime(item.created_at)}</span>
                  </li>
                ))}
              </ul>
            </Section>
          )}

          <Section title="Job description">
            {job.jd_full ? (
              <p className="max-h-72 overflow-y-auto whitespace-pre-wrap text-sm leading-relaxed text-muted">
                {job.jd_full}
              </p>
            ) : (
              <p className="text-sm text-faint">
                The description couldn't be retrieved, so this job was scored mostly from
                its title. Open the posting to read it.
              </p>
            )}
          </Section>
        </>
      )}
    </Dialog>
  )
}
