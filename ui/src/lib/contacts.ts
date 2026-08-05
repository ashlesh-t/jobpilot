/** HR/recruiter contacts — CRUD plus a CSV/XLSX bulk import. */
import { useMutation, useQuery, useQueryClient } from '@tanstack/react-query'

import { api } from './api'

export interface Contact {
  id: number
  company: string
  name: string
  email: string
  role: string
  source: string
  created_at: string | null
}

const KEY = ['contacts'] as const

export function useContacts() {
  return useQuery({
    queryKey: KEY,
    queryFn: () => api.get<{ contacts: Contact[] }>('/api/contacts'),
    select: (data) => data.contacts,
  })
}

export function useCreateContact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (body: { company: string; name?: string; email?: string; role?: string }) =>
      api.post<Contact>('/api/contacts', body),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useDeleteContact() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (id: number) => api.del(`/api/contacts/${id}`),
    onSuccess: () => qc.invalidateQueries({ queryKey: KEY }),
  })
}

export function useImportContacts() {
  const qc = useQueryClient()
  return useMutation({
    mutationFn: (file: File) => {
      const form = new FormData()
      form.append('file', file)
      return api.upload<{ imported: number; skipped: number; errors: string[]; contacts: Contact[] }>(
        '/api/contacts/import',
        form,
      )
    },
    onSuccess: () => {
      qc.invalidateQueries({ queryKey: KEY })
      qc.invalidateQueries({ queryKey: ['jobs'] })
    },
  })
}
