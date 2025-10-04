import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { translateDeviceError } from '@/lib/errors';

const ALLOWED_ACTIONS = new Set(['start', 'stop', 'reload']);

export async function POST(request: NextRequest, { params }: { params: { deviceId: string; action: string } }) {
  const { deviceId, action } = params;
  if (!ALLOWED_ACTIONS.has(action)) {
    return NextResponse.json({ message: 'Aktion nicht erlaubt' }, { status: 400 });
  }

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: `/api/player/${action}`,
      method: 'POST',
      request
    });

    const text = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, text || 'Aktion fehlgeschlagen');
      return NextResponse.json({ message }, { status: response.status });
    }

    let payload: unknown = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        console.error('Failed to parse player response', error);
      }
    }

    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Player action failed', error);
    return NextResponse.json({ message: 'Aktion fehlgeschlagen' }, { status: 500 });
  }
}
