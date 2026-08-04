/** Job sources step of the setup wizard — Apify + Adzuna, both optional. Native
 *  scrapers (RemoteOK, Internshala, ...) need no configuration and already run. */
import { SecretsVault } from '@/components/settings/SecretsVault'

const APIFY_SIGNUP_URL = 'https://console.apify.com/settings/integrations'
const ADZUNA_SIGNUP_URL = 'https://developer.adzuna.com/signup'
const ADZUNA_ADMIN_URL = 'https://developer.adzuna.com/admin/'

function Qr({ data }: { data: string }) {
  return (
    <img
      src={`/api/qr?data=${encodeURIComponent(data)}`}
      alt="QR code"
      width={112}
      height={112}
      className="rounded-lg border border-line bg-white p-1.5"
    />
  )
}

export function SourcesStep() {
  return (
    <div className="space-y-5">
      <p className="text-sm text-muted">
        JobPilot already scrapes ~8 sources for free. An Apify token adds LinkedIn,
        Naukri, Glassdoor and Indeed; Adzuna adds another free source on top of the
        built-in scrapers.
      </p>

      <div className="rounded-xl border border-line p-4">
        <h3 className="text-sm font-semibold text-ink">Get a free Apify token</h3>
        <p className="mt-1 text-sm text-muted">
          Get a free token at{' '}
          <a
            className="text-accent hover:underline"
            href={APIFY_SIGNUP_URL}
            target="_blank"
            rel="noreferrer"
          >
            {APIFY_SIGNUP_URL}
          </a>
        </p>
        <div className="mt-3">
          <Qr data={APIFY_SIGNUP_URL} />
        </div>
      </div>

      <div className="rounded-xl border border-line p-4">
        <h3 className="text-sm font-semibold text-ink">Get Adzuna credentials</h3>
        <ol className="mt-2 list-decimal space-y-1 pl-5 text-sm text-muted">
          <li>
            Register for free at{' '}
            <a
              className="text-accent hover:underline"
              href={ADZUNA_SIGNUP_URL}
              target="_blank"
              rel="noreferrer"
            >
              {ADZUNA_SIGNUP_URL}
            </a>{' '}
            — no card needed
          </li>
          <li>
            Your App ID and App Key are both shown at{' '}
            <a
              className="text-accent hover:underline"
              href={ADZUNA_ADMIN_URL}
              target="_blank"
              rel="noreferrer"
            >
              {ADZUNA_ADMIN_URL}
            </a>
          </li>
          <li>Paste each one below</li>
        </ol>
        <p className="mt-2 text-sm text-muted">
          Free tier is 1,000 calls/month — plenty for a couple of runs a day.
        </p>
        <div className="mt-3">
          <Qr data={ADZUNA_SIGNUP_URL} />
        </div>
      </div>

      <SecretsVault groups={['scraping']} />
    </div>
  )
}
