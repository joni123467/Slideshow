'use client';

import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { zodResolver } from '@hookform/resolvers/zod';
import { playbackSchema, type PlaybackPayload } from '@/lib/validation';
import { useRouter } from 'next/navigation';

interface PlaybackFormProps {
  deviceId: string;
  initialValues: PlaybackPayload;
}

export function PlaybackForm({ deviceId, initialValues }: PlaybackFormProps) {
  const router = useRouter();
  const [error, setError] = useState<string | null>(null);
  const [isSubmitting, setSubmitting] = useState(false);

  const {
    register,
    handleSubmit,
    watch,
    formState: { errors, isDirty }
  } = useForm<PlaybackPayload>({
    resolver: zodResolver(playbackSchema),
    defaultValues: initialValues
  });

  const onSubmit = handleSubmit(async (values) => {
    setSubmitting(true);
    setError(null);
    try {
      const response = await fetch(`/api/devices/${deviceId}/playback`, {
        method: 'PUT',
        headers: {
          'Content-Type': 'application/json'
        },
        body: JSON.stringify(values)
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({}));
        throw new Error(data?.message ?? 'Speichern fehlgeschlagen');
      }
      router.refresh();
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Unbekannter Fehler');
    } finally {
      setSubmitting(false);
    }
  });

  const transitionType = watch('transition_type');

  return (
    <form onSubmit={onSubmit} className="space-y-6">
      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Bilddauer (Sekunden)</label>
          <input
            type="number"
            step={1}
            min={1}
            {...register('image_duration', { valueAsNumber: true })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
          {errors.image_duration && <p className="text-xs text-red-400">{errors.image_duration.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Bildrotation</label>
          <input
            type="number"
            min={0}
            max={359}
            {...register('image_rotation', { valueAsNumber: true })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
          {errors.image_rotation && <p className="text-xs text-red-400">{errors.image_rotation.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Bildmodus</label>
          <select {...register('image_fit')} className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm">
            <option value="contain">contain</option>
            <option value="stretch">stretch</option>
            <option value="original">original</option>
          </select>
          {errors.image_fit && <p className="text-xs text-red-400">{errors.image_fit.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Übergang</label>
          <select {...register('transition_type')} className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm">
            <option value="cut">cut</option>
            <option value="fade">fade</option>
            <option value="slide">slide</option>
            <option value="zoom">zoom</option>
          </select>
          {errors.transition_type && <p className="text-xs text-red-400">{errors.transition_type.message}</p>}
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Übergangsdauer (Sek.)</label>
          <input
            type="number"
            step={0.1}
            min={0.2}
            max={10}
            {...register('transition_duration', { valueAsNumber: true })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
          {errors.transition_duration && <p className="text-xs text-red-400">{errors.transition_duration.message}</p>}
        </div>
      </div>

      <div>
        <label className="mb-1 block text-sm font-medium text-slate-300">Splitscreen Quellen</label>
        <input
          type="text"
          placeholder="Quelle1, Quelle2"
          {...register('splitscreen_sources', {
            setValueAs: (value) =>
              typeof value === 'string'
                ? value
                    .split(',')
                    .map((item) => item.trim())
                    .filter(Boolean)
                : value
          })}
          className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
        />
        {errors.splitscreen_sources && <p className="text-xs text-red-400">{errors.splitscreen_sources.message}</p>}
      </div>

      <div className="grid gap-4 md:grid-cols-2">
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Video Player Args</label>
          <textarea
            rows={3}
            {...register('video_player_args', {
              setValueAs: (value) =>
                typeof value === 'string'
                  ? value
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean)
                  : value
            })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">Ein Argument pro Zeile.</p>
        </div>
        <div>
          <label className="mb-1 block text-sm font-medium text-slate-300">Image Viewer Args</label>
          <textarea
            rows={3}
            {...register('image_viewer_args', {
              setValueAs: (value) =>
                typeof value === 'string'
                  ? value
                      .split('\n')
                      .map((item) => item.trim())
                      .filter(Boolean)
                  : value
            })}
            className="w-full rounded-md border border-slate-700 bg-slate-950 p-2 text-sm"
          />
          <p className="mt-1 text-xs text-slate-500">Ein Argument pro Zeile.</p>
        </div>
      </div>

      {transitionType === 'fade' && (
        <p className="text-xs text-slate-500">
          Hinweis: Fade-Effekte benötigen ggf. zusätzliche Video-Player Argumente.
        </p>
      )}

      {error && <p className="text-sm text-red-400">{error}</p>}

      <div className="flex justify-end gap-2">
        <button
          type="button"
          onClick={() => router.refresh()}
          className="rounded-md border border-slate-700 px-4 py-2 text-sm text-slate-300 hover:border-slate-500 hover:text-white"
        >
          Zurücksetzen
        </button>
        <button
          type="submit"
          disabled={!isDirty || isSubmitting}
          className="rounded-md bg-sky-500 px-4 py-2 text-sm font-semibold text-slate-950 hover:bg-sky-400 disabled:cursor-not-allowed disabled:bg-slate-700"
        >
          {isSubmitting ? 'Speichern…' : 'Speichern'}
        </button>
      </div>
    </form>
  );
}
