import { NextRequest, NextResponse } from 'next/server';
import { proxyDeviceRequest } from '@/lib/proxy';

export async function POST(request: NextRequest) {
  const body = await request.json().catch(() => ({}));
  const deviceId = body.deviceId ?? request.nextUrl.searchParams.get('device');
  const sessionCookieName = process.env.SLIDESHOW_MANAGER_SESSION_COOKIE ?? 'slideshow_manager_session';

  try {
    const activeDevice = deviceId ?? request.cookies.get('slideshow_active_device')?.value;
    if (activeDevice) {
      await proxyDeviceRequest({ deviceId: activeDevice, path: '/logout', method: 'POST', request });
    }
  } catch (error) {
    console.error('Logout proxy failed', error);
  }

  const response = NextResponse.json({ success: true });
  response.cookies.delete('slideshow_active_device');
  response.cookies.set({
    name: sessionCookieName,
    value: '',
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    path: '/',
    maxAge: 0
  });
  return response;
}
