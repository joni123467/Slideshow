'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { z } from 'zod';
import { zodResolver } from '@hookform/resolvers/zod';

const schema = z.object({
  deviceId: z.string().min(1, 'Bitte Gerät wählen'),
  username: z.string().min(1, 'Benutzername angeben'),
  password: z.string().min(1, 'Passwort angeben')
});

type FormValues = z.infer<typeof schema>;

type Props = {
  devices: Array<{ id: string; name: string }>;
};

export function LoginForm({ devices }: Props) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    formState: { errors }
  } = useForm<FormValues>({
    resolver: zodResolver(schema),
    defaultValues: {
      deviceId: devices[0]?.id ?? '',
      username: '',
      password: ''
    }
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch('/api/auth/login', {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(values)
      });

      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.message ?? 'Login fehlgeschlagen');
      }

      router.push(`/dashboard?device=${encodeURIComponent(values.deviceId)}`);
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="space-y-1">
        <label className="block text-sm font-medium text-slate-300">Gerät</label>
        <select
          {...register('deviceId')}
          className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
        >
          {devices.map((device) => (
            <option key={device.id} value={device.id}>
              {device.name}
            </option>
          ))}
        </select>
        {errors.deviceId && <p className="text-xs text-red-400">{errors.deviceId.message}</p>}
      </div>

      <div className="space-y-1">
        <label className="block text-sm font-medium text-slate-300">Benutzername</label>
        <input
          {...register('username')}
          type="text"
          className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          autoComplete="username"
        />
        {errors.username && <p className="text-xs text-red-400">{errors.username.message}</p>}
      </div>

      <div className="space-y-1">
        <label className="block text-sm font-medium text-slate-300">Passwort</label>
        <input
          {...register('password')}
          type="password"
          className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          autoComplete="current-password"
        />
        {errors.password && <p className="text-xs text-red-400">{errors.password.message}</p>}
      </div>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <button
        type="submit"
        className="flex w-full items-center justify-center rounded-md bg-sky-500 py-2 text-sm font-semibold text-slate-950 transition hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-700"
        disabled={isSubmitting}
      >
        {isSubmitting ? 'Anmeldung…' : 'Anmelden'}
      </button>
    </form>
  );
}
