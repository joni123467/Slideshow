# Slideshow Manager

A Next.js App Router project that manages one or more Slideshow appliances through a secure proxy. The project mirrors the feature set of the existing Flask-based Slideshow UI while adding fleet management tooling.

## Features

- Secure proxy layer that mirrors the native device API (state, config, playback, sources, media preview, logs, config import/export).
- HttpOnly session cookie management that stores the device session on the server side only.
- React Query powered dashboard with polling, cache invalidation and optimistic UI states.
- React Hook Form + Zod driven forms aligned with the API constraints for playback and source management.
- Multi-device registry with role-based access hooks and optional audit logging stubs.
- Modular UI components that can be themed and localized.

## Getting Started

1. **Install dependencies**

   ```bash
   pnpm install
   # or
   npm install
   ```

2. **Environment variables**

   Copy the example environment file and adapt it to your deployment.

   ```bash
   cp .env.example .env.local
   ```

   | Variable | Description |
   | --- | --- |
   | `SLIDESHOW_MANAGER_DEVICE_REGISTRY` | JSON string that defines allowed devices (see `.env.example`). |
   | `SLIDESHOW_MANAGER_SESSION_COOKIE` | Name of the HttpOnly cookie that stores the proxied device session. |
   | `SLIDESHOW_MANAGER_ALLOWED_HOSTS` | Comma separated whitelist of device hostnames/IPs for SSRF protection. |
   | `NEXTAUTH_SECRET` | Secret used to encrypt cookies (fallback for custom auth helpers). |

3. **Development server**

   ```bash
   pnpm run dev
   ```

4. **Testing**

   ```bash
   pnpm run lint
   pnpm run test
   ```

## Project Structure

- `app/` – Next.js App Router routes for UI and API proxy handlers.
- `components/` – Reusable UI and form components.
- `lib/` – Shared utilities for configuration, validation, proxy logic and auth helpers.
- `server/` – Server-only helpers (audit logging, scheduler stubs).
- `tests/` – Unit and integration tests (Jest + Testing Library stubs).

## Roadmap

- Implement advanced fleet dashboards and scheduling UIs.
- Connect audit log stubs to a persistent datastore (SQL/Prisma).
- Add end-to-end tests using Playwright.
- Harden import/export streaming with resumable uploads.

## License

MIT

