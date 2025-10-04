import Link from 'next/link';
import { notFound } from 'next/navigation';
import { getDeviceById, getDeviceRegistry } from '@/lib/devices';
import { proxyJson } from '@/lib/proxy';

export default async function DashboardPage({
  searchParams
}: {
  searchParams: { device?: string };
}) {
  const deviceId = searchParams.device ?? getDeviceRegistry()[0]?.id;
  if (!deviceId) {
    notFound();
  }

  const device = getDeviceById(deviceId);
  const [state, config] = await Promise.all([
    proxyJson<any>({ deviceId, path: '/api/state' }),
    proxyJson<any>({ deviceId, path: '/api/config' })
  ]);

  return (
    <main className="mx-auto flex w-full max-w-6xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-2 lg:flex-row lg:items-center lg:justify-between">
        <div>
          <h1 className="text-3xl font-semibold">{device.name}</h1>
          <p className="text-sm text-slate-400">Host: {device.host}</p>
        </div>
        <nav className="flex items-center gap-3 text-sm">
          <Link href={`/dashboard?device=${deviceId}`} className="text-slate-300 hover:text-white">
            Dashboard
          </Link>
          <Link href={`/devices/${deviceId}/playback`} className="text-slate-300 hover:text-white">
            Wiedergabe
          </Link>
          <Link href={`/devices/${deviceId}/sources`} className="text-slate-300 hover:text-white">
            Quellen
          </Link>
          <form action="/api/auth/logout" method="post">
            <button className="rounded-md border border-slate-700 px-3 py-1 text-slate-300 hover:border-slate-500 hover:text-white">
              Logout
            </button>
          </form>
        </nav>
      </header>

      <section className="grid gap-4 md:grid-cols-2 xl:grid-cols-3">
        <article className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="text-lg font-semibold text-slate-100">Gerätestatus</h2>
          <dl className="mt-3 space-y-2 text-sm text-slate-300">
            <div className="flex justify-between">
              <dt>Online</dt>
              <dd>{state.online ? 'Ja' : 'Nein'}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Service</dt>
              <dd>{state.service_state}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Version</dt>
              <dd>{state.version}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Theme</dt>
              <dd>{state.theme}</dd>
            </div>
          </dl>
        </article>

        <article className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="text-lg font-semibold text-slate-100">Aktuelle Wiedergabe</h2>
          <dl className="mt-3 space-y-2 text-sm text-slate-300">
            <div className="flex justify-between">
              <dt>Quelle</dt>
              <dd>{state.playback?.source ?? '–'}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Bilddauer</dt>
              <dd>{config.playback?.image_duration ?? '–'} Sekunden</dd>
            </div>
            <div className="flex justify-between">
              <dt>Übergang</dt>
              <dd>{config.playback?.transition_type ?? '–'}</dd>
            </div>
            <div className="flex justify-between">
              <dt>Splitscreen</dt>
              <dd>{config.playback?.splitscreen_sources?.join(', ') ?? 'Deaktiviert'}</dd>
            </div>
          </dl>
        </article>

        <article className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="text-lg font-semibold text-slate-100">Letzte Aktionen</h2>
          <ul className="mt-3 space-y-2 text-sm text-slate-300">
            {(state.audit_log ?? []).slice(0, 5).map((entry: any) => (
              <li key={entry.id} className="rounded-md bg-slate-950/60 p-2">
                <p className="font-medium">{entry.action}</p>
                <p className="text-xs text-slate-500">{entry.user ?? 'System'} – {entry.timestamp}</p>
              </li>
            ))}
            {(!state.audit_log || state.audit_log.length === 0) && <li className="text-slate-500">Keine Aktivitäten.</li>}
          </ul>
        </article>
      </section>
    </main>
  );
}
