import { ComingSoon } from './ComingSoon'

export function SettingsPage() {
  return (
    <ComingSoon
      title="Settings"
      description="How JobPilot itself behaves."
      planned={[
        'Choose and authenticate your AI backend',
        'Switch between PostgreSQL and SQLite storage',
        'Adjust model pricing used by the cost meter',
        'Export or reset your data',
      ]}
    />
  )
}
