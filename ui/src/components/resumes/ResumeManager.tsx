/** Resume library — drag-and-drop upload, folders, and exactly one active resume.
 *
 *  The active resume is a single global choice, so it is rendered as one radio group
 *  spanning every folder: whichever radio is filled in is the resume JobPilot reads and
 *  tailors from. A row of look-alike "Use this" buttons couldn't say that. */
import clsx from 'clsx'
import {
  Download,
  FileText,
  FolderPen,
  FolderPlus,
  Pencil,
  Sparkles,
  Trash2,
  Upload,
} from 'lucide-react'
import { useRef, useState } from 'react'

import { HelpTip } from '@/components/ui/Help'
import { useToast } from '@/components/ui/Toast'
import {
  Card,
  Chip,
  Dialog,
  EmptyState,
  Field,
  SkeletonRows,
  Spinner,
} from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { relativeTime } from '@/lib/format'
import {
  useActivateResume,
  useDeleteResume,
  useExtractProfile,
  useRenameFolder,
  useRenameResume,
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

/** Mirrors `safe_name()` in core/repo/resumes.py, so the UI rejects what the server would. */
const FOLDER_RE = /^[A-Za-z0-9._-]+$/

function folderError(name: string, existing: string[]): string | null {
  if (!name) return 'Give the folder a name.'
  if (!FOLDER_RE.test(name)) return 'Letters, numbers, dots, dashes and underscores only.'
  if (existing.includes(name)) return 'You already have a folder with that name.'
  return null
}

export function ResumeManager({ onExtracted }: { onExtracted?: () => void }) {
  const { data, isLoading } = useResumes()
  const upload = useUploadResume()
  const activate = useActivateResume()
  const remove = useDeleteResume()
  const extract = useExtractProfile()
  const renameFolder = useRenameFolder()
  const renameResume = useRenameResume()
  const toast = useToast()

  const inputRef = useRef<HTMLInputElement>(null)
  const [folder, setFolder] = useState('default')
  const [draftFolders, setDraftFolders] = useState<string[]>([])
  const [dragging, setDragging] = useState(false)
  const [newFolderOpen, setNewFolderOpen] = useState(false)
  const [renaming, setRenaming] = useState<string | null>(null)
  const [pendingDelete, setPendingDelete] = useState<Resume | null>(null)
  const [labelDraft, setLabelDraft] = useState<{ id: number; value: string } | null>(null)
  const [extractingId, setExtractingId] = useState<number | null>(null)

  const existingFolders = data?.folders.map((f) => f.folder) ?? []
  const folderOptions = Array.from(new Set(['default', ...existingFolders, ...draftFolders]))

  const doUpload = async (file: File) => {
    try {
      const res = await upload.mutateAsync({ file, folder })
      setDraftFolders((prev) => prev.filter((f) => f !== res.resume.folder))
      toast.success(
        res.resume.is_active
          ? `${res.resume.filename} uploaded and set as your active resume.`
          : `${res.resume.filename} uploaded into ${res.resume.folder}.`,
      )
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Upload failed.')
    }
  }

  const doExtract = async (resume: Resume) => {
    setExtractingId(resume.id)
    try {
      const res = await extract.mutateAsync(resume.id)
      // A heuristic read means the AI backend never ran. Saying "success" there would
      // hide a regex-guessed profile that quietly degrades every later score.
      if (res.source === 'heuristic') {
        toast.error(`Read ${resume.filename} without the AI backend — ${res.detail}`)
      } else {
        toast.success(`Profile drafted from ${resume.filename} — ${res.detail}`)
      }
      onExtracted?.()
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not read that resume.')
    } finally {
      setExtractingId(null)
    }
  }

  const doActivate = (resume: Resume) => {
    if (resume.is_active) return
    activate.mutate(resume.id, {
      onError: (e) =>
        toast.error(e instanceof ApiError ? e.detail : 'Could not switch resume.'),
    })
  }

  const saveLabel = () => {
    if (!labelDraft) return
    const { id, value } = labelDraft
    setLabelDraft(null)
    renameResume.mutate(
      { id, label: value.trim() },
      { onError: (e) => toast.error(e instanceof ApiError ? e.detail : 'Rename failed.') },
    )
  }

  return (
    <>
      <Card
        title="Your resumes"
        subtitle="Pick the one JobPilot reads and tailors from — the filled circle is active"
        actions={
          <>
            <label className="flex items-center gap-2 text-xs text-muted">
              Upload into
              <select
                className="input w-auto"
                value={folder}
                onChange={(e) => setFolder(e.target.value)}
              >
                {folderOptions.map((f) => (
                  <option key={f} value={f}>
                    {f}
                  </option>
                ))}
              </select>
            </label>
            <button
              type="button"
              className="btn-ghost btn-sm"
              onClick={() => setNewFolderOpen(true)}
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
            <div className="space-y-5" role="radiogroup" aria-label="Active resume">
              {data.folders.map((group) => (
                <section key={group.folder}>
                  <h3 className="mb-2 flex items-center gap-2 text-xs font-semibold uppercase tracking-wide text-muted">
                    {group.folder}
                    <span className="font-normal normal-case tracking-normal text-faint">
                      {group.resumes.length} file{group.resumes.length === 1 ? '' : 's'}
                    </span>
                    <button
                      type="button"
                      className="btn-icon"
                      title={`Rename the ${group.folder} folder`}
                      onClick={() => setRenaming(group.folder)}
                    >
                      <FolderPen className="h-3.5 w-3.5" />
                    </button>
                  </h3>
                  <ul>
                    {group.resumes.map((resume) => (
                      <li
                        key={resume.id}
                        className={clsx(
                          'flex flex-wrap items-center gap-3 rounded-lg border-t border-line px-2 py-3 first:border-t-0',
                          resume.is_active && 'bg-accent-soft/30',
                        )}
                      >
                        <input
                          type="radio"
                          name="active-resume"
                          className="h-4 w-4 shrink-0 accent-[rgb(var(--accent))]"
                          checked={resume.is_active}
                          disabled={resume.missing || activate.isPending}
                          onChange={() => doActivate(resume)}
                          aria-label={`Use ${resume.filename}`}
                        />
                        <FileText
                          className={clsx(
                            'h-4 w-4 shrink-0',
                            resume.is_active ? 'text-accent' : 'text-faint',
                          )}
                        />
                        <div className="min-w-0 flex-1">
                          {labelDraft?.id === resume.id ? (
                            <input
                              className="input h-8 py-1 text-sm"
                              autoFocus
                              value={labelDraft.value}
                              placeholder="A name you'll recognise"
                              onChange={(e) =>
                                setLabelDraft({ id: resume.id, value: e.target.value })
                              }
                              onBlur={saveLabel}
                              onKeyDown={(e) => {
                                if (e.key === 'Enter') saveLabel()
                                if (e.key === 'Escape') setLabelDraft(null)
                              }}
                            />
                          ) : (
                            <p className="flex items-center gap-2 truncate text-sm text-ink">
                              {resume.label || resume.filename}
                              {resume.is_active && (
                                <Chip tone="accent">
                                  <span className="flex items-center gap-1">
                                    Active <HelpTip id="resume.active" />
                                  </span>
                                </Chip>
                              )}
                              {resume.missing && <Chip tone="danger">File missing</Chip>}
                              <button
                                type="button"
                                className="btn-icon"
                                title="Rename"
                                onClick={() =>
                                  setLabelDraft({ id: resume.id, value: resume.label })
                                }
                              >
                                <Pencil className="h-3 w-3" />
                              </button>
                            </p>
                          )}
                          <p className="text-xs text-faint">
                            {resume.label ? `${resume.filename} · ` : ''}
                            {humanSize(resume.size)} · uploaded{' '}
                            {relativeTime(resume.uploaded_at)}
                          </p>
                        </div>

                        <div className="flex shrink-0 items-center gap-1">
                          {!resume.missing && (
                            <>
                              <button
                                type="button"
                                className="btn-secondary btn-sm"
                                onClick={() => doExtract(resume)}
                                disabled={extract.isPending}
                                title="Read this resume and draft your profile"
                              >
                                {extractingId === resume.id ? (
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
                            onClick={() => setPendingDelete(resume)}
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

      <NewFolderDialog
        open={newFolderOpen}
        existing={folderOptions}
        onClose={() => setNewFolderOpen(false)}
        onCreate={(name) => {
          setDraftFolders((prev) => [...prev, name])
          setFolder(name)
          setNewFolderOpen(false)
          toast.info(`Uploads will go into ${name}. It appears once the first file lands.`)
        }}
      />

      <RenameFolderDialog
        folder={renaming}
        existing={existingFolders}
        onClose={() => setRenaming(null)}
        onRename={(oldName, newName) => {
          setRenaming(null)
          renameFolder.mutate(
            { oldName, newName },
            {
              onSuccess: () => {
                if (folder === oldName) setFolder(newName)
                toast.success(`Renamed to ${newName}.`)
              },
              onError: (e) =>
                toast.error(e instanceof ApiError ? e.detail : 'Rename failed.'),
            },
          )
        }}
      />

      <Dialog
        open={pendingDelete !== null}
        onClose={() => setPendingDelete(null)}
        title="Delete this resume?"
        subtitle={pendingDelete?.filename}
        size="sm"
        footer={
          <>
            <button
              type="button"
              className="btn-secondary"
              onClick={() => setPendingDelete(null)}
            >
              Keep it
            </button>
            <button
              type="button"
              className="btn-danger"
              onClick={() => {
                const target = pendingDelete
                setPendingDelete(null)
                if (target) remove.mutate(target.id)
              }}
            >
              Delete
            </button>
          </>
        }
      >
        <p className="text-sm text-muted">
          The file is removed from disk as well.
          {pendingDelete?.is_active &&
            ' This is your active resume — the most recent remaining one takes over.'}
        </p>
      </Dialog>
    </>
  )
}

function NewFolderDialog({
  open,
  existing,
  onClose,
  onCreate,
}: {
  open: boolean
  existing: string[]
  onClose: () => void
  onCreate: (name: string) => void
}) {
  const [name, setName] = useState('')
  const [touched, setTouched] = useState(false)
  const error = folderError(name.trim(), existing)

  const submit = () => {
    setTouched(true)
    if (!error) {
      onCreate(name.trim())
      setName('')
      setTouched(false)
    }
  }

  return (
    <Dialog
      open={open}
      onClose={onClose}
      title="New folder"
      subtitle="Group resumes by the kind of role you're aiming at"
      size="sm"
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit}>
            Create
          </button>
        </>
      }
    >
      <Field
        label="Folder name"
        error={touched ? (error ?? undefined) : undefined}
        hint="e.g. backend, data-science, internships"
      >
        <input
          className="input"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder="backend"
        />
      </Field>
      <p className="mt-3 text-xs text-faint">
        Folders are just how your files are grouped on disk — this one shows up in the list
        as soon as you upload something into it.
      </p>
    </Dialog>
  )
}

function RenameFolderDialog({
  folder,
  existing,
  onClose,
  onRename,
}: {
  folder: string | null
  existing: string[]
  onClose: () => void
  onRename: (oldName: string, newName: string) => void
}) {
  const [name, setName] = useState('')
  const [touched, setTouched] = useState(false)
  const others = existing.filter((f) => f !== folder)
  const error = folderError(name.trim(), others)

  const submit = () => {
    setTouched(true)
    if (!error && folder) {
      onRename(folder, name.trim())
      setName('')
      setTouched(false)
    }
  }

  return (
    <Dialog
      open={folder !== null}
      onClose={onClose}
      title={`Rename “${folder ?? ''}”`}
      size="sm"
      footer={
        <>
          <button type="button" className="btn-secondary" onClick={onClose}>
            Cancel
          </button>
          <button type="button" className="btn-primary" onClick={submit}>
            Rename
          </button>
        </>
      }
    >
      <Field label="New name" error={touched ? (error ?? undefined) : undefined}>
        <input
          className="input"
          autoFocus
          value={name}
          onChange={(e) => setName(e.target.value)}
          onKeyDown={(e) => e.key === 'Enter' && submit()}
          placeholder={folder ?? ''}
        />
      </Field>
      <p className="mt-3 text-xs text-faint">
        The folder on disk is renamed too, and every resume inside it moves with it.
      </p>
    </Dialog>
  )
}
