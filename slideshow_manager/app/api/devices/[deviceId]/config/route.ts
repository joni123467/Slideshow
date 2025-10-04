import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { translateDeviceError } from '@/lib/errors';

export async function GET(_: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;

  try {
    const response = await proxyDeviceRequest({ deviceId, path: '/api/config' });
    const body = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, body || 'Konfiguration konnte nicht geladen werden');
      return NextResponse.json({ message }, { status: response.status });
    }
    let json: unknown = {};
    if (body) {
      try {
        json = JSON.parse(body);
      } catch (error) {
        console.error('Failed to parse config response', error);
      }
    }
    const res = NextResponse.json(json);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Config proxy failed', error);
    return NextResponse.json({ message: 'Konfiguration konnte nicht geladen werden' }, { status: 500 });
  }
}
