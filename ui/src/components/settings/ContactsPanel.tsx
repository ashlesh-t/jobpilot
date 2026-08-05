/** HR/recruiter contacts — bulk import from a spreadsheet, matched to jobs by
 *  company name so a job's detail view can offer a referral draft automatically. */
import { Trash2, Upload } from 'lucide-react'
import { useRef } from 'react'

import { useToast } from '@/components/ui/Toast'
import { Card, SkeletonRows } from '@/components/ui/primitives'
import { ApiError } from '@/lib/api'
import { useContacts, useDeleteContact, useImportContacts } from '@/lib/contacts'

export function ContactsPanel() {
  const { data: contacts, isLoading } = useContacts()
  const importContacts = useImportContacts()
  const deleteContact = useDeleteContact()
  const toast = useToast()
  const inputRef = useRef<HTMLInputElement>(null)

  const onImport = async (file: File) => {
    try {
      const result = await importContacts.mutateAsync(file)
      toast.success(
        `Imported ${result.imported} contact${result.imported === 1 ? '' : 's'}` +
          (result.skipped ? ` — skipped ${result.skipped} row(s) with no company or email.` : '.'),
      )
    } catch (e) {
      toast.error(e instanceof ApiError ? e.detail : 'Could not import that file.')
    }
  }

  return (
    <Card
      title="Contacts"
      subtitle="HR/recruiter contacts, matched to jobs by company — used to draft referral requests"
      actions={
        <button
          type="button"
          className="btn-secondary btn-sm"
          onClick={() => inputRef.current?.click()}
          disabled={importContacts.isPending}
        >
          <Upload className="h-3.5 w-3.5" />
          {importContacts.isPending ? 'Importing…' : 'Import CSV/XLSX'}
        </button>
      }
    >
      <input
        ref={inputRef}
        type="file"
        className="hidden"
        accept=".csv,.xlsx"
        onChange={(e) => {
          const file = e.target.files?.[0]
          if (file) onImport(file)
          e.target.value = ''
        }}
      />

      {isLoading ? (
        <SkeletonRows rows={3} />
      ) : !contacts?.length ? (
        <p className="text-sm text-faint">
          No contacts yet. Import a spreadsheet with company, name, email and role columns.
        </p>
      ) : (
        <div className="table-wrap">
          <table className="w-full">
            <thead>
              <tr>
                <th className="th">Company</th>
                <th className="th">Name</th>
                <th className="th">Email</th>
                <th className="th">Role</th>
                <th className="th"></th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((c) => (
                <tr key={c.id}>
                  <td className="td">{c.company}</td>
                  <td className="td">{c.name || '—'}</td>
                  <td className="td">{c.email || '—'}</td>
                  <td className="td">{c.role || '—'}</td>
                  <td className="td">
                    <button
                      type="button"
                      className="btn-icon"
                      onClick={() => deleteContact.mutate(c.id)}
                      aria-label={`Remove ${c.name || c.company}`}
                    >
                      <Trash2 className="h-3.5 w-3.5" />
                    </button>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  )
}
