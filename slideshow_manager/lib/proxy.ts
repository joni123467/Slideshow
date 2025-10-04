import { NextRequest, NextResponse } from 'next/server';
import { assertAllowedHost, getDeviceById } from './devices';
import { cookies } from 'next/headers';

const DEFAULT_TIMEOUT = 8000;

type ProxyOptions = {
  deviceId: string;
  path: string;
  method?: string;
  body?: BodyInit | null;
  headers?: HeadersInit;
  request?: NextRequest;
};

function getSessionCookieName() {
  return process.env.SLIDESHOW_MANAGER_SESSION_COOKIE ?? 'slideshow_manager_session';
}

async function fetchWithTimeout(url: string, options: RequestInit = {}) {
  const controller = new AbortController();
  const timeout = setTimeout(() => controller.abort(), DEFAULT_TIMEOUT);

  try {
    const response = await fetch(url, {
      ...options,
      signal: controller.signal
    });
    return response;
  } finally {
    clearTimeout(timeout);
  }
}

export async function proxyDeviceRequest<T = unknown>({
  deviceId,
  path,
  method = 'GET',
  body,
  headers,
  request
}: ProxyOptions): Promise<Response> {
  const device = getDeviceById(deviceId);
  assertAllowedHost(device.host);
  const url = new URL(path, device.host).toString();

  const sessionCookieName = getSessionCookieName();
  const cookieSource = request ? request.cookies : cookies();
  const sessionCookie = cookieSource.get(sessionCookieName);

  const upstreamHeaders = new Headers(headers);
  upstreamHeaders.set('Accept', 'application/json, text/plain, */*');
  upstreamHeaders.set('User-Agent', 'Slideshow Manager Proxy');

  if (sessionCookie?.value) {
    try {
      const stored = JSON.parse(sessionCookie.value) as string[];
      if (stored.length > 0) {
        upstreamHeaders.set('Cookie', stored.join('; '));
      }
    } catch (error) {
      console.error('Failed to parse stored session cookie', error);
    }
  }

  if (request) {
    const incomingHeaders = request.headers;
    const contentType = incomingHeaders.get('content-type');
    if (contentType) {
      upstreamHeaders.set('Content-Type', contentType);
    }
  }

  const response = await fetchWithTimeout(url, {
    method,
    headers: upstreamHeaders,
    body,
    redirect: 'manual'
  });

  return response;
}

export async function proxyJson<T = unknown>(options: ProxyOptions): Promise<T> {
  const response = await proxyDeviceRequest(options);
  if (!response.ok) {
    const errorBody = await response.text();
    throw new Error(errorBody || response.statusText);
  }
  const contentType = response.headers.get('content-type');
  if (contentType?.includes('application/json')) {
    return (await response.json()) as T;
  }
  throw new Error('Unexpected content type from device');
}

export function extractSessionCookies(response: Response): string[] {
  const setCookieHeader = response.headers.get('set-cookie');
  if (!setCookieHeader) {
    return [];
  }
  return setCookieHeader
    .split(/,(?=[^,]+=)/g)
    .map((entry) => entry.split(';')[0]?.trim())
    .filter(Boolean) as string[];
}

export function applySessionCookies(nextResponse: NextResponse, upstream: Response) {
  const cookies = extractSessionCookies(upstream);
  if (cookies.length === 0) {
    return;
  }
  const sessionCookieName = getSessionCookieName();
  nextResponse.cookies.set({
    name: sessionCookieName,
    value: JSON.stringify(cookies),
    httpOnly: true,
    secure: true,
    sameSite: 'lax',
    path: '/'
  });
}
