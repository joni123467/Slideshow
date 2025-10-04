import { NextRequest, NextResponse } from 'next/server';
import { applySessionCookies, proxyDeviceRequest } from '@/lib/proxy';

export async function GET(request: NextRequest, { params }: { params: { deviceId: string; logName: string } }) {
  const { deviceId, logName } = params;

  const response = await proxyDeviceRequest({
    deviceId,
    path: `/logs/${encodeURIComponent(logName)}/download`,
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
