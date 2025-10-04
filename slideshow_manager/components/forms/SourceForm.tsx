'use client';

import { useState } from 'react';
import { useRouter } from 'next/navigation';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { sourceSchema, type SourcePayload } from '@/lib/validation';

interface SourceFormProps {
  deviceId: string;
  initialValues?: Partial<SourcePayload>;
}

export function SourceForm({ deviceId, initialValues }: SourceFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);
  const {
    register,
    handleSubmit,
    reset,
    formState: { errors }
  } = useForm<SourcePayload>({
    resolver: zodResolver(sourceSchema),
    defaultValues: {
      auto_scan: false,
      ...(initialValues as SourcePayload)
    }
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/devices/${deviceId}/sources`, {
        method: 'POST',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(values)
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.message ?? 'Quelle konnte nicht gespeichert werden');
      }
      reset();
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setSubmitting(false);
    }
  });

  return (
    <form onSubmit={onSubmit} className="space-y-4">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Name</label>
          <input
            {...register('name')}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
          {errors.name && <p className="text-xs text-red-400">{errors.name.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Typ</label>
          <select {...register('kind')} className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm">
            <option value="filesystem">Filesystem</option>
            <option value="network">Netzwerk</option>
          </select>
          {errors.kind && <p className="text-xs text-red-400">{errors.kind.message}</p>}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-slate-300">Pfad</label>
        <input
          {...register('path')}
          className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
        />
        {errors.path && <p className="text-xs text-red-400">{errors.path.message}</p>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Benutzername</label>
          <input {...register('username')} className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm" />
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Passwort</label>
          <input
            type="password"
            {...register('password')}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
        </div>
      </div>

      <label className="inline-flex items-center gap-2 text-sm text-slate-300">
        <input
          type="checkbox"
          {...register('auto_scan', {
            setValueAs: (value) => value === true || value === 'on'
          })}
        />{' '}
        Automatisch scannen
      </label>

      {error && <p className="text-sm text-red-400">{error}</p>}

      <button
        type="submit"
        disabled={isSubmitting}
        className="rounded-md bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-700"
      >
        {isSubmitting ? 'Speichern…' : 'Quelle speichern'}
      </button>
    </form>
  );
}
