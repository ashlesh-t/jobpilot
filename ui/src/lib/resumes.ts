/** Resume library hooks. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'
import { settingsKeys } from './settings'
import type { Profile } from './settings'

export interface Resume {
  id: number
  folder: string
  filename: string
  label: string
  path: string
  suffix: string
  hash: string
  is_active: boolean
  uploaded_at: string | null
  size: number
  missing: boolean
}

export interface ResumeLibrary {
  folders: { folder: string; resumes: Resume[] }[]
  resumes: Resume[]
  active: Resume | null
  allowed: string[]
}

export function useResumes() {
  return useQuery({
    queryKey: ['resumes'],
    queryFn: () => api.get<ResumeLibrary>('/api/resumes'),
  })
}

function useResumeInvalidation() {
  const qc = useQueryClient()
  return () => {
    qc.invalidateQueries({ queryKey: ['resumes'] })
    qc.invalidateQueries({ queryKey: settingsKeys.setup })
    qc.invalidateQueries({ queryKey: settingsKeys.preferences })
    qc.invalidateQueries({ queryKey: ['doctor'] })
  }
}

export function useUploadResume() {
  const invalidate = useResumeInvalidation()
  return useMutation({
    mutationFn: ({ file, folder, makeActive = true }: {
      file: File
      folder: string
      makeActive?: boolean
    }) => {
      const form = new FormData()
      form.append('file', file)
      form.append('folder', folder)
      form.append('make_active', String(makeActive))
      return api.upload<{ resume: Resume; resumes: Resume[] }>('/api/resumes/upload', form)
    },
    onSuccess: invalidate,
  })
}

export function useActivateResume() {
  const invalidate = useResumeInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.post<{ resume: Resume }>(`/api/resumes/${id}/activate`),
    onSuccess: invalidate,
  })
}

export function useDeleteResume() {
  const invalidate = useResumeInvalidation()
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/resumes/${id}`),
    onSuccess: invalidate,
  })
}

export function useRenameResume() {
  const invalidate = useResumeInvalidation()
  return useMutation({
    mutationFn: ({ id, label }: { id: number; label: string }) =>
      api.patch<{ resume: Resume }>(`/api/resumes/${id}`, { label }),
    onSuccess: invalidate,
  })
}

export function useRenameFolder() {
  const invalidate = useResumeInvalidation()
  return useMutation({
    mutationFn: ({ oldName, newName }: { oldName: string; newName: string }) =>
      api.post('/api/resumes/folders/rename', { old: oldName, new: newName }),
    onSuccess: invalidate,
  })
}

export function useExtractProfile() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) =>
      api.post<{ profile: Profile; source: string; detail: string; characters: number }>(
        `/api/resumes/${id}/extract`,
      ),
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: settingsKeys.profile })
      qc.invalidateQueries({ queryKey: settingsKeys.setup })
    },
  })
}
