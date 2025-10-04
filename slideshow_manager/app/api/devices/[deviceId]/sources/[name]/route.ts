import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { sourceSchema } from '@/lib/validation';
import { translateDeviceError } from '@/lib/errors';

export async function PUT(request: NextRequest, { params }: { params: { deviceId: string; name: string } }) {
  const { deviceId, name } = params;
  const json = await request.json();
  const parseResult = sourceSchema.partial().safeParse(json);

  if (!parseResult.success) {
    return NextResponse.json({ message: 'Ungültige Eingaben', errors: parseResult.error.flatten() }, { status: 400 });
  }

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: `/api/sources/${encodeURIComponent(name)}`,
      method: 'PUT',
      body: JSON.stringify(parseResult.data),
      headers: {
        'Content-Type': 'application/json'
      },
      request
    });
    const text = await response.text();
    if (!response.ok) {
      const message = translateDeviceError(response.status, text || 'Quelle konnte nicht aktualisiert werden');
      return NextResponse.json({ message }, { status: response.status });
    }
    let payload: unknown = {};
    if (text) {
      try {
        payload = JSON.parse(text);
      } catch (error) {
        console.error('Failed to parse source update response', error);
      }
    }
    const res = NextResponse.json(payload);
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Source update failed', error);
    return NextResponse.json({ message: 'Quelle konnte nicht aktualisiert werden' }, { status: 500 });
  }
}

export async function POST(request: NextRequest, context: { params: { deviceId: string; name: string } }) {
  const methodOverride = request.nextUrl.searchParams.get('_method');
  if (methodOverride?.toUpperCase() === 'DELETE') {
    return DELETE(request, context);
  }
  return NextResponse.json({ message: 'Nicht unterstützt' }, { status: 405 });
}

export async function DELETE(_: NextRequest, { params }: { params: { deviceId: string; name: string } }) {
  const { deviceId, name } = params;

  try {
    const response = await proxyDeviceRequest({
      deviceId,
      path: `/api/sources/${encodeURIComponent(name)}`,
      method: 'DELETE'
    });
    if (!response.ok) {
      const text = await response.text();
      const message = translateDeviceError(response.status, text || 'Quelle konnte nicht gelöscht werden');
      return NextResponse.json({ message }, { status: response.status });
    }
    const res = NextResponse.json({ success: true });
    applySessionCookies(res, response);
    return res;
  } catch (error) {
    console.error('Source delete failed', error);
    return NextResponse.json({ message: 'Quelle konnte nicht gelöscht werden' }, { status: 500 });
  }
}
