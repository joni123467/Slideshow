import { describe, expect, it } from '@jest/globals';
import { playbackSchema } from '@/lib/validation';

describe('validation', () => {
  it('rejects invalid durations', () => {
    const result = playbackSchema.safeParse({
      image_duration: 0,
      image_fit: 'contain',
      image_rotation: 0,
      transition_type: 'cut',
      transition_duration: 0.2
    });
    expect(result.success).toBe(false);
  });

  it('accepts minimal valid payload', () => {
    const result = playbackSchema.safeParse({
      image_duration: 5,
      image_fit: 'contain',
      image_rotation: 0,
      transition_type: 'cut',
      transition_duration: 1
    });
    expect(result.success).toBe(true);
  });
});
