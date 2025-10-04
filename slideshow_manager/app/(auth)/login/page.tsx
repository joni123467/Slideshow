import { LoginForm } from '@/components/forms/LoginForm';
import { getDeviceRegistry } from '@/lib/devices';

export default function LoginPage() {
  const devices = getDeviceRegistry();
  const hasDevices = devices.length > 0;
  return (
    <main className="flex min-h-screen items-center justify-center p-6">
      <div className="w-full max-w-md rounded-lg border border-slate-800 bg-slate-900 p-8 shadow-xl">
        <h1 className="mb-6 text-2xl font-semibold">Sign in to Slideshow Manager</h1>
        {hasDevices ? (
          <LoginForm devices={devices} />
        ) : (
          <p className="text-sm text-red-400">
            Keine Geräte konfiguriert. Hinterlege SLIDESHOW_MANAGER_DEVICE_REGISTRY in der Umgebung.
          </p>
        )}
      </div>
    </main>
  );
}
