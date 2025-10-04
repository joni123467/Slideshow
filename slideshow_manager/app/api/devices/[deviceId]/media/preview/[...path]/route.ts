import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';

export async function GET(request: NextRequest, {
  params
}: {
  params: { deviceId: string; path: string[] };
}) {
  const { deviceId, path } = params;
  const encodedPath = path.map((segment) => encodeURIComponent(segment)).join('/');
  const url = `/media/preview/${encodedPath}`;

  const response = await proxyDeviceRequest({
    deviceId,
    path: url,
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
