import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';

export async function GET(request: NextRequest, { params }: { params: { deviceId: string } }) {
  const { deviceId } = params;

  const response = await proxyDeviceRequest({
    deviceId,
    path: '/config/export',
    headers: request.headers,
    request
  });

  const headers = new Headers(response.headers);
  headers.delete('set-cookie');
  const res = new NextResponse(response.body, {
    status: response.status,
    headers
  });
  applySessionCookies(res, response);
  return res;
}
