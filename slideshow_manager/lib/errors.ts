export class HttpError extends Error {
  public status: number;

  constructor(status: number, message: string) {
    super(message);
    this.status = status;
  }
}

export function translateDeviceError(status: number, fallback: string): string {
  switch (status) {
    case 400:
      return 'Die Anfrage war ungültig. Bitte Eingaben prüfen.';
    case 401:
      return 'Sitzung ist abgelaufen oder ungültig. Bitte erneut anmelden.';
    case 404:
      return 'Die angefragte Ressource wurde nicht gefunden.';
    case 415:
      return 'Der Medientyp wird nicht unterstützt (415).';
    case 429:
      return 'Zu viele Anfragen. Bitte später erneut versuchen.';
    case 500:
    default:
      return fallback;
  }
}
