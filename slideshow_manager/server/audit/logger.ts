import crypto from 'node:crypto';

export type AuditEntry = {
  id: string;
  user: string;
  deviceId: string;
  action: string;
  payloadHash?: string;
  timestamp: string;
};

const auditLog: AuditEntry[] = [];

export function recordAuditEntry(entry: Omit<AuditEntry, 'id' | 'timestamp'>) {
  const now = new Date().toISOString();
  const newEntry: AuditEntry = {
    id: crypto.randomUUID(),
    timestamp: now,
    ...entry
  };
  auditLog.push(newEntry);
  if (auditLog.length > 1000) {
    auditLog.shift();
  }
  return newEntry;
}

export function listAuditEntries(limit = 100) {
  return auditLog.slice(-limit).reverse();
}
