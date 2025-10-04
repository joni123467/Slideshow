import { NextResponse } from 'next/server';
import type { NextRequest } from 'next/server';

const PROTECTED_PATHS = ['/dashboard', '/devices'];

export function middleware(request: NextRequest) {
  const sessionCookieName = process.env.SLIDESHOW_MANAGER_SESSION_COOKIE ?? 'slideshow_manager_session';
  const session = request.cookies.get(sessionCookieName);

  const isProtected = PROTECTED_PATHS.some((path) => request.nextUrl.pathname.startsWith(path));
  if (isProtected && !session) {
    const loginUrl = new URL('/login', request.url);
    loginUrl.searchParams.set('next', request.nextUrl.pathname);
    return NextResponse.redirect(loginUrl);
  }

  return NextResponse.next();
}

export const config = {
  matcher: ['/dashboard/:path*', '/devices/:path*']
};
