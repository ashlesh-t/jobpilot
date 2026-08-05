/** About-page data: what this install is, and what changed between versions. */
import { useQuery } from '@tanstack/react-query'

import { api } from './api'

export interface ToolRow {
  name: string
  found: boolean
  detail: string
  required: boolean
  hint: string
}

export interface About {
  version: string
  python: string
  platform: string
  install_source: 'pipx' | 'pip' | 'local' | 'checkout'
  data_dir: string
  db_backend: string
  db_url: string
  repo_url: string
  issues_url: string
  tools: ToolRow[]
}

export interface ReleaseSection {
  heading: string
  items: string[]
  body: string[]
}

export interface Release {
  version: string
  date: string
  title: string
  kind: string
  sections: ReleaseSection[]
}

export function useAbout() {
  return useQuery({
    queryKey: ['about'],
    queryFn: () => api.get<About>('/api/about'),
    staleTime: 60_000,
  })
}

export function useChangelog() {
  return useQuery({
    queryKey: ['about', 'changelog'],
    queryFn: () =>
      api.get<{
        current: string
        releases: Release[]
        bundled: boolean
        newer: string[]
      }>('/api/about/changelog'),
    staleTime: 5 * 60_000,
  })
}
