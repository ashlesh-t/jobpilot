/** Resume library — drag-and-drop upload, folders, and exactly one active resume. */
import clsx from 'clsx'
import {
  Check,
  Download,
  FileText,
  FolderPlus,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { useRef, useState } from 'react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import { Card, Chip, EmptyState, SkeletonRows, Spinner } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import {
  useActivateResume,
  useDeleteResume,
  useExtractProfile,
  useResumes,
  useUploadResume,
} from '@/lib/resumes'
import type { Resume } from '@/lib/resumes'

function humanSize(bytes: number): string {
  if (!bytes) return '—'
  if (bytes < 1024) return `${bytes} B`
  if (bytes < 1024 * 1024) return `${Math.round(bytes / 1024)} KB`
  return `${(bytes / 1024 / 1024).toFixed(1)} MB`
}

export function ResumeManager({ onExtracted }: { onExtracted?: () => void }) {
  const { data, isLoading } = useResumes()
  const upload = useUploadResume()
  const activate = useActivateResume()
  const remove = useDeleteResume()
  const extract = useExtractProfile()
  const toast = useToast()

  const inputRef = useRef<HTMLInputElement>(null)
  const [folder, setFolder] = useState('default')
  const [dragging, setDragging] = useState(false)

  const existingFolders = data?.folders.map((f) => f.folder) ?? []

  const doUpload = async (file: File) => {
    try {
      const res = await upload.mutateAsync({ file, folder })
      toast.success(
        res.resume.is_active
          ? `${res.resume.filename} uploaded and set as your active resume.`
          : `${res.resume.filename} uploaded.`,
      )
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Upload failed.')
    }
  }

  const doExtract = async (resume: Resume) => {
    try {
      const res = await extract.mutateAsync(resume.id)
      toast.success(`Profile drafted from ${resume.filename} — ${res.detail}`)
      onExtracted?.()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not read that resume.')
    }
  }

  return (
    <Card
      title="Your resumes"
      subtitle="One is active — that's the one JobPilot reads and tailors from"
      actions={
        <>
          <select
            className="input w-auto"
            value={folder}
            onChange={(e) => setFolder(e.target.value)}
            aria-label="Upload into folder"
          >
            {Array.from(new Set(['default', ...existingFolders])).map((f) => (
              <option key={f} value={f}>
                {f}
              </option>
            ))}
          </select>
          <button
            type="button"
            className="btn-ghost btn-sm"
            onClick={() => {
              const name = window.prompt('Name the new folder')?.trim()
              if (name) setFolder(name)
            }}
            title="Upload into a new folder"
          >
            <FolderPlus className="h-3.5 w-3.5" />
            New folder
          </button>
        </>
      }
    >
      {/* Drop zone */}
      <div
        onDragOver={(e) => {
          e.preventDefault()
          setDragging(true)
        }}
        onDragLeave={() => setDragging(false)}
        onDrop={(e) => {
          e.preventDefault()
          setDragging(false)
          const file = e.dataTransfer.files?.[0]
          if (file) doUpload(file)
        }}
        className={clsx(
          'flex flex-col items-center gap-2 rounded-xl border-2 border-dashed px-6 py-8 text-center transition-colors',
          dragging ? 'border-accent bg-accent-soft/50' : 'border-line',
        )}
      >
        {upload.isPending ? (
          <>
            <Spinner />
            <p className="text-sm text-muted">Uploading…</p>
          </>
        ) : (
          <>
            <Upload className="h-5 w-5 text-faint" />
            <p className="text-sm text-ink">
              Drop a resume here, or{' '}
              <button
                type="button"
                className="font-medium text-accent hover:underline"
                onClick={() => inputRef.current?.click()}
              >
                choose a file
              </button>
            </p>
            <p className="text-xs text-faint">
              {(data?.allowed ?? ['.pdf', '.docx', '.tex']).join(' · ')} — up to 15 MB.
              Uploading into <span className="font-medium">{folder}</span>.
            </p>
          </>
        )}
        <input
          ref={inputRef}
          type="file"
          className="hidden"
          accept={(data?.allowed ?? []).join(',')}
          onChange={(e) => {
            const file = e.target.files?.[0]
            if (file) doUpload(file)
            e.target.value = ''
          }}
        />
      </div>

      {/* Library */}
      <div className="mt-5">
        {isLoading ? (
          <SkeletonRows rows={3} />
        ) : !data?.resumes.length ? (
          <EmptyState
            icon={<FileText className="h-5 w-5" />}
            title="No resumes yet"
            description="Upload one to get started — JobPilot reads it to build your profile."
          />
        ) : (
          <div className="space-y-5">
            {data.folders.map((group) => (
              <section key={group.folder}>
                <h3 className="mb-2 text-xs font-semibold uppercase tracking-wide text-muted">
                  {group.folder}
                </h3>
                <ul>
                  {group.resumes.map((resume) => (
                    <li
                      key={resume.id}
                      className="flex flex-wrap items-center gap-3 border-t border-line py-3 first:border-t-0 first:pt-0"
                    >
                      <FileText
                        className={clsx(
                          'h-4 w-4 shrink-0',
                          resume.is_active ? 'text-accent' : 'text-faint',
                        )}
                      />
                      <div className="min-w-0 flex-1">
                        <p className="flex items-center gap-2 truncate text-sm text-ink">
                          {resume.filename}
                          {resume.is_active && (
                            <Chip tone="accent">
                              <span className="flex items-center gap-1">
                                Active <HelpTip id="resume.active" />
                              </span>
                            </Chip>
                          )}
                          {resume.missing && <Chip tone="danger">File missing</Chip>}
                        </p>
                        <p className="text-xs text-faint">
                          {humanSize(resume.size)} · uploaded {relativeTime(resume.uploaded_at)}
                        </p>
                      </div>

                      <div className="flex shrink-0 items-center gap-1">
                        {!resume.is_active && !resume.missing && (
                          <button
                            type="button"
                            className="btn-secondary btn-sm"
                            onClick={() => activate.mutate(resume.id)}
                            disabled={activate.isPending}
                          >
                            <Check className="h-3.5 w-3.5" />
                            Use this
                          </button>
                        )}
                        {!resume.missing && (
                          <>
                            <button
                              type="button"
                              className="btn-secondary btn-sm"
                              onClick={() => doExtract(resume)}
                              disabled={extract.isPending}
                              title="Read this resume and draft your profile"
                            >
                              {extract.isPending ? (
                                <Spinner className="h-3.5 w-3.5" />
                              ) : (
                                <Sparkles className="h-3.5 w-3.5" />
                              )}
                              Read it
                            </button>
                            <a
                              href={`/api/resumes/${resume.id}/download`}
                              className="btn-icon"
                              title="Download"
                            >
                              <Download className="h-3.5 w-3.5" />
                            </a>
                          </>
                        )}
                        <button
                          type="button"
                          className="btn-icon hover:text-danger"
                          title="Delete"
                          onClick={() => {
                            if (window.confirm(`Delete ${resume.filename}?`)) {
                              remove.mutate(resume.id)
                            }
                          }}
                        >
                          <Trash2 className="h-3.5 w-3.5" />
                        </button>
                      </div>
                    </li>
                  ))}
                </ul>
              </section>
            ))}
          </div>
        )}
      </div>
    </Card>
  )
}
