import { z } from 'zod';

export const playbackSchema = z.object({
  image_duration: z.number().int().min(1).max(3600),
  image_fit: z.enum(['contain', 'stretch', 'original']),
  image_rotation: z.number().int().min(0).max(359),
  transition_type: z.enum(['cut', 'fade', 'slide', 'zoom']),
  transition_duration: z.number().min(0.2).max(10),
  splitscreen_sources: z.array(z.string()).max(4).optional(),
  video_player_args: z.array(z.string()).optional(),
  image_viewer_args: z.array(z.string()).optional()
});

export type PlaybackPayload = z.infer<typeof playbackSchema>;

export const sourceSchema = z.object({
  name: z.string().min(1),
  kind: z.enum(['filesystem', 'network']),
  path: z.string().min(1),
  username: z.string().optional(),
  password: z.string().optional(),
  auto_scan: z.boolean().default(false)
});

export type SourcePayload = z.infer<typeof sourceSchema>;
