import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { sourceSchema } from '@/lib/validation';
import { translateDeviceError } from '@/lib/errors';

export async function GET(_: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;

  try {
    const response = await proxyDeviceRequest({ deviceId, path: '/api/sources' });
    const text = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, text || 'Quellen konnten nicht geladen werden');
      return NextResponse.json({ message }, { status: response.status });
    }
    let payload: unknown = [];
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        console.error('Failed to parse sources response', error);
      }
    }
    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Sources fetch failed', error);
    return NextResponse.json({ message: 'Quellen konnten nicht geladen werden' }, { status: 500 });
  }
}

export async function POST(request: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;
  const json = await request.json();
  const parseResult = sourceSchema.safeParse(json);

  if (!parseResult.success) {
    return NextResponse.json({ message: 'Ungültige Eingaben', errors: parseResult.error.flatten() }, { status: 400 });
  }

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: '/api/sources',
      method: 'POST',
      body: JSON.stringify(parseResult.data),
      headers: {
        'Content-Type': 'application/json'
      },
      request
    });
    const text = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, text || 'Quelle konnte nicht gespeichert werden');
      return NextResponse.json({ message }, { status: response.status });
    }
    let payload: unknown = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        console.error('Failed to parse source create response', error);
      }
    }
    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Source create failed', error);
    return NextResponse.json({ message: 'Quelle konnte nicht gespeichert werden' }, { status: 500 });
  }
}
