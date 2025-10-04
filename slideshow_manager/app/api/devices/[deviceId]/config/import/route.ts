import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { translateDeviceError } from '@/lib/errors';

export async function POST(request: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;
  const formData = await request.formData();

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: '/config/import',
      method: 'POST',
      body: formData,
      request
    });
    const text = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, text || 'Import fehlgeschlagen');
      return NextResponse.json({ message }, { status: response.status });
    }
    let payload: unknown = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        console.error('Failed to parse import response', error);
      }
    }
    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Config import failed', error);
    return NextResponse.json({ message: 'Import fehlgeschlagen' }, { status: 500 });
  }
}
