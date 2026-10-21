export type Data = Record<string, any>;
export type SmokEvent = { type: string; data: Data };
export async function api<T = any>(path: string, method = 'GET', body?: unknown): Promise<T> {
  const response = await fetch('/api' + path, {
    method,
    headers: body === undefined ? {} : { 'Content-Type': 'application/json' },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  const result = await response.json();
  if (!response.ok)
    throw new Error(
      typeof result.detail === 'string'
        ? result.detail
        : 'The request could not be completed. Check the form values.',
    );
  return result;
}
export function mergeEvent(events: SmokEvent[], event: SmokEvent): SmokEvent[] {
  const last = events.at(-1);
  if (
    event.type === 'text_delta' &&
    last?.type === 'text_delta' &&
    last.data.worker === event.data.worker
  )
    return [
      ...events.slice(0, -1),
      {
        ...event,
        data: { ...event.data, text: (last.data.text + event.data.text).slice(-100000) },
      },
    ];
  return [...events, event].slice(-400);
}
export const number = (n: number = 0) =>
  new Intl.NumberFormat('en-US', {
    notation: n >= 10000 ? 'compact' : 'standard',
    maximumFractionDigits: 1,
  }).format(n);
export const money = (n: number = 0) => '$' + n.toFixed(n > 0 && n < 0.01 ? 4 : 2);
