import { Link } from 'react-router-dom'

import { Card, EmptyState } from '@/components/ui/primitives'

export function NotFoundPage() {
  return (
    <Card className="mt-10">
      <EmptyState
        title="That page doesn't exist"
        description="The link may be out of date, or the page may have moved."
        action={
          <Link to="/" className="btn-primary btn-sm">
            Back to Home
          </Link>
        }
      />
    </Card>
  )
}
