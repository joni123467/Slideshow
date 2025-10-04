import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';
import { translateDeviceError } from '@/lib/errors';
import { getDeviceById } from '@/lib/devices';

export async function POST(request: NextRequest) {
  const body = await request.json();
  const { deviceId, username, password } = body as {
    deviceId?: string;
    username?: string;
    password?: string;
  };

  if (!deviceId || !username || !password) {
    return NextResponse.json({ message: 'Gerät, Benutzername und Passwort erforderlich.' }, { status: 400 });
  }

  try {
    const device = getDeviceById(deviceId);
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);

    const response = await proxyDeviceRequest({
      deviceId: device.id,
      path: '/login',
      method: 'POST',
      body: formData,
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded'
      },
      request
    });

    if (!response.ok) {
      const text = await response.text();
      const message = translateDeviceError(response.status, text || 'Anmeldung fehlgeschlagen');
      return NextResponse.json({ message }, { status: response.status });
    }

    const res = NextResponse.json({ success: true }, { status: 200 });
    applySessionCookies(res, response);
    res.cookies.set('slideshow_active_device', device.id, {
      httpOnly: false,
      sameSite: 'lax',
      path: '/'
    });
    return res;
  } catch (error) {
    console.error('Login error', error);
    return NextResponse.json({ message: 'Login fehlgeschlagen.' }, { status: 500 });
  }
}
