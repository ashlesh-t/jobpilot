/** Placeholder for pages whose epic hasn't landed yet.
 *
 *  Deliberately explicit about what will be here and what to do meanwhile — a page that
 *  just says "coming soon" leaves the user guessing whether the feature is broken. */
import { Construction } from 'lucide-react'
import type { ReactNode } from 'react'
import { Link } from 'react-router-dom'

import { PageHeader } from '@/components/layout/PageHeader'
import { Card, EmptyState } from '@/components/ui/primitives'

export function ComingSoon({
  title,
  description,
  planned,
  meanwhile,
}: {
  title: string
  description: string
  planned: string[]
  meanwhile?: ReactNode
}) {
  return (
    <>
      <PageHeader title={title} description={description} />
      <Card>
        <EmptyState
          icon={<Construction className="h-5 w-5" />}
          title="This page is still being built"
          description={
            <>
              <span className="mb-3 block">It will let you:</span>
              <ul className="mx-auto max-w-sm space-y-1.5 text-left">
                {planned.map((item) => (
                  <li key={item} className="flex gap-2">
                    <span className="text-faint">•</span>
                    <span>{item}</span>
                  </li>
                ))}
              </ul>
            </>
          }
          action={
            meanwhile ?? (
              <Link to="/" className="btn-secondary btn-sm">
                Back to Home
              </Link>
            )
          }
        />
      </Card>
    </>
  )
}
