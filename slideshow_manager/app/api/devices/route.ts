import { NextResponse } from 'next/server';
import { getDeviceRegistry } from '@/lib/devices';

export function GET() {
  const devices = getDeviceRegistry();
  return NextResponse.json(devices);
}
