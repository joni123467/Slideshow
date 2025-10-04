import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { translateDeviceError } from '@/lib/errors';

export async function POST(request: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;
  const body = await request.json().catch(() => ({}));
  const { enabled } = body as { enabled?: boolean };

  if (typeof enabled !== 'boolean') {
    return NextResponse.json({ message: 'enabled muss true oder false sein' }, { status: 400 });
  }

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: '/api/player/info-screen',
      method: 'POST',
      body: JSON.stringify({ enabled }),
      headers: {
        'Content-Type': 'application/json'
      },
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
        console.error('Failed to parse info screen response', error);
      }
    }

    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Info screen toggle failed', error);
    return NextResponse.json({ message: 'Aktion fehlgeschlagen' }, { status: 500 });
  }
}
