import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { playbackSchema } from '@/lib/validation';
import { translateDeviceError } from '@/lib/errors';

export async function PUT(request: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;
  const json = await request.json();
  const parseResult = playbackSchema.safeParse(json);

  if (!parseResult.success) {
    return NextResponse.json({ message: 'Ungültige Eingaben', errors: parseResult.error.flatten() }, { status: 400 });
  }

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: '/api/playback',
      method: 'PUT',
      body: JSON.stringify(parseResult.data),
      headers: {
        'Content-Type': 'application/json'
      },
      request
    });

    const text = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, text || 'Wiedergabe konnte nicht gespeichert werden');
      return NextResponse.json({ message }, { status: response.status });
    }

    let payload: unknown = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        console.error('Failed to parse playback response', error);
      }
    }

    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Playback update failed', error);
    return NextResponse.json({ message: 'Wiedergabe konnte nicht gespeichert werden' }, { status: 500 });
  }
}
