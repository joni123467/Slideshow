import Link from 'next/link';
import { notFound } from 'next/navigation';
import { PlaybackForm } from '@/components/forms/PlaybackForm';
import { getDeviceById } from '@/lib/devices';
import { proxyJson } from '@/lib/proxy';

export default async function PlaybackPage({
  params
}: {
  params: { deviceId: string };
}) {
  const deviceId = params.deviceId;
  if (!deviceId) {
    notFound();
  }
  const device = getDeviceById(deviceId);
  const config = await proxyJson<any>({ deviceId, path: '/api/config' });
  const playback = config.playback;

  return (
    <main className="mx-auto flex w-full max-w-3xl flex-col gap-6 p-6">
      <header className="flex flex-col gap-1">
        <h1 className="text-3xl font-semibold">Wiedergabe – {device.name}</h1>
        <p className="text-sm text-slate-400">Passe die Wiedergabeparameter des Geräts an.</p>
        <nav className="mt-2 flex gap-3 text-sm">
          <Link href={`/dashboard?device=${deviceId}`} className="text-slate-300 hover:text-white">
            Zurück zum Dashboard
          </Link>
          <Link href={`/devices/${deviceId}/sources`} className="text-slate-300 hover:text-white">
            Quellenverwaltung
          </Link>
        </nav>
      </header>
      <section className="rounded-lg border border-slate-800 bg-slate-900 p-6">
        <PlaybackForm deviceId={deviceId} initialValues={playback} />
      </section>
    </main>
  );
}
