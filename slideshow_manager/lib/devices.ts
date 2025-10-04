import { headers } from 'next/headers';

export type DeviceDefinition = {
  id: string;
  name: string;
  host: string;
  notes?: string;
};

const registryCache = new Map<string, DeviceDefinition>();

function parseRegistry(): DeviceDefinition[] {
  if (process.env.SLIDESHOW_MANAGER_DEVICE_REGISTRY) {
    try {
      const parsed = JSON.parse(process.env.SLIDESHOW_MANAGER_DEVICE_REGISTRY) as DeviceDefinition[];
      if (!Array.isArray(parsed)) {
        throw new Error('Registry must be an array');
      }
      parsed.forEach((device) => {
        if (!device.id || !device.host) {
          throw new Error('Device must include id and host');
        }
        registryCache.set(device.id, device);
      });
      return parsed;
    } catch (error) {
      throw new Error(`Failed to parse SLIDESHOW_MANAGER_DEVICE_REGISTRY: ${(error as Error).message}`);
    }
  }

  return [];
}

export function getDeviceRegistry(): DeviceDefinition[] {
  if (registryCache.size > 0) {
    return Array.from(registryCache.values());
  }
  return parseRegistry();
}

export function getDeviceById(deviceId: string): DeviceDefinition {
  const existing = registryCache.get(deviceId);
  if (existing) {
    return existing;
  }
  const registry = parseRegistry();
  const device = registry.find((entry) => entry.id === deviceId);
  if (!device) {
    throw new Error(`Unknown device ${deviceId}`);
  }
  registryCache.set(device.id, device);
  return device;
}

export function assertAllowedHost(host: string) {
  const allowedHosts = process.env.SLIDESHOW_MANAGER_ALLOWED_HOSTS?.split(',').map((item) => item.trim()).filter(Boolean);
  if (!allowedHosts || allowedHosts.length === 0) {
    return;
  }
  const url = new URL(host);
  if (!allowedHosts.includes(url.hostname)) {
    throw new Error(`Host ${url.hostname} is not permitted by SLIDESHOW_MANAGER_ALLOWED_HOSTS`);
  }
}

export function getActiveDeviceIdFromHeaders(): string | null {
  const deviceHeader = headers().get('x-slideshow-device');
  if (deviceHeader) {
    return deviceHeader;
  }
  const cookie = headers().get('cookie');
  if (!cookie) {
    return null;
  }
  const searchParams = new URLSearchParams(cookie.replace(/;\s*/g, '&'));
  return searchParams.get('slideshow_active_device');
}
