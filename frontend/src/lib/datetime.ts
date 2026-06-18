export interface DateTimeFormatOptions {
  month?: "numeric" | "2-digit" | "long" | "short" | "narrow";
  day?: "numeric" | "2-digit";
  hour?: "numeric" | "2-digit";
  minute?: "numeric" | "2-digit";
  second?: "numeric" | "2-digit";
}

const TIMEZONE_PATTERN = /(?:Z|[+-]\d{2}:\d{2})$/i;
const DATE_TIME_WITHOUT_TIMEZONE_PATTERN = /^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}(?::\d{2}(?:\.\d+)?)?$/;

export function parseApiDateTime(value: string | null | undefined): Date | null {
  if (!value) return null;
  const normalized = DATE_TIME_WITHOUT_TIMEZONE_PATTERN.test(value) && !TIMEZONE_PATTERN.test(value)
    ? `${value}Z`
    : value;
  const date = new Date(normalized);
  return Number.isNaN(date.getTime()) ? null : date;
}

export function apiDateTimeMs(value: string | null | undefined): number {
  return parseApiDateTime(value)?.getTime() || 0;
}

export function formatDateTimeLocal(
  value: string | null | undefined,
  options: DateTimeFormatOptions = {
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
  },
): string {
  const date = parseApiDateTime(value);
  if (!date) return value || "-";
  return date.toLocaleString("zh-CN", options).replace(/\//g, "/");
}
