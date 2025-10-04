import Link from 'next/link';
import { notFound } from 'next/navigation';
import { SourceForm } from '@/components/forms/SourceForm';
import { getDeviceById } from '@/lib/devices';
import { proxyJson } from '@/lib/proxy';

export default async function SourcesPage({
  params
}: {
  params: { deviceId: string };
}) {
  const deviceId = params.deviceId;
  if (!deviceId) {
    notFound();
  }
  const device = getDeviceById(deviceId);
  const sources = await proxyJson<any>({ deviceId, path: '/api/sources' });

  return (
    <main className="mx-auto flex w-full max-w-5xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold">Quellen – {device.name}</h1>
        <p className="text-sm text-slate-400">Verwalte Medienquellen und Auto-Scan Einstellungen.</p>
        <nav className="mt-2 flex gap-3 text-sm">
          <Link href={`/dashboard?device=${deviceId}`} className="text-slate-300 hover:text-white">
            Zurück zum Dashboard
          </Link>
          <Link href={`/devices/${deviceId}/playback`} className="text-slate-300 hover:text-white">
            Wiedergabe
          </Link>
        </nav>
      </header>

      <section className="grid gap-6 lg:grid-cols-[2fr,1fr]">
        <div className="space-y-3">
          {sources.length === 0 && <p className="text-sm text-slate-500">Noch keine Quellen angelegt.</p>}
          {sources.map((source: any) => (
            <article key={source.name} className="rounded-lg border border-slate-800 bg-slate-900 p-4">
              <header className="flex items-center justify-between">
                <div>
                  <h2 className="text-lg font-semibold text-slate-100">{source.name}</h2>
                  <p className="text-xs text-slate-500">{source.kind} – {source.path}</p>
                </div>
                <form
                  action={`/api/devices/${deviceId}/sources/${encodeURIComponent(source.name)}?_method=DELETE`}
                  method="post"
                >
                  <button className="rounded-md border border-red-600 px-3 py-1 text-xs text-red-400 hover:bg-red-600/20">
                    Löschen
                  </button>
                </form>
              </header>
              <dl className="mt-3 grid gap-2 text-xs text-slate-400 md:grid-cols-2">
                <div>
                  <dt>Auto Scan</dt>
                  <dd>{source.auto_scan ? 'Aktiv' : 'Inaktiv'}</dd>
                </div>
                <div>
                  <dt>Benutzername</dt>
                  <dd>{source.username ?? '–'}</dd>
                </div>
              </dl>
            </article>
          ))}
        </div>
        <aside className="rounded-lg border border-slate-800 bg-slate-900 p-4">
          <h2 className="text-lg font-semibold text-slate-100">Neue Quelle</h2>
          <SourceForm deviceId={deviceId} />
        </aside>
      </section>
    </main>
  );
}
