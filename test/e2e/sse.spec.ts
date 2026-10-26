import { expect, test } from '@playwright/test';
import { DEFAULT_TICKERS } from '../helpers/api';
import { startStreamProxy } from '../helpers/proxy';
import { expectConnected } from '../helpers/ui';

test.describe('SSE price stream', () => {
  test('stream sends well-formed events about every 500ms', async ({ baseURL }) => {
    const controller = new AbortController();
    const res = await fetch(`${baseURL}/api/stream/prices`, { signal: controller.signal });
    try {
      expect(res.status).toBe(200);
      expect(res.headers.get('content-type')).toContain('text/event-stream');
      expect(res.headers.get('cache-control')).toContain('no-cache');

      const reader = res.body!.getReader();
      const decoder = new TextDecoder();
      let buffer = '';
      const events: Record<string, Record<string, unknown>>[] = [];
      const started = Date.now();
      while (events.length < 4 && Date.now() - started < 10_000) {
        const { value, done } = await reader.read();
        if (done) break;
        buffer += decoder.decode(value, { stream: true });
        let idx: number;
        while ((idx = buffer.indexOf('\n\n')) !== -1) {
          const block = buffer.slice(0, idx);
          buffer = buffer.slice(idx + 2);
          const data = block
            .split('\n')
            .filter((l) => l.startsWith('data:'))
            .map((l) => l.slice(5).trim())
            .join('\n');
          if (data) events.push(JSON.parse(data));
        }
      }
      const elapsed = Date.now() - started;

      expect(events.length).toBeGreaterThanOrEqual(4);
      expect(elapsed, '4 events should arrive within ~2-4s').toBeLessThan(5_000);

      const last = events[events.length - 1];
      for (const ticker of DEFAULT_TICKERS) {
        const update = last[ticker] as Record<string, unknown>;
        expect(update, `event includes ${ticker}`).toBeTruthy();
        expect(update).toMatchObject({ ticker });
        for (const key of ['price', 'previous_price', 'open_price', 'change', 'change_pct']) {
          expect(typeof update[key], `${ticker}.${key}`).toBe('number');
        }
        expect(update.price as number).toBeGreaterThan(0);
        expect(['up', 'down', 'flat']).toContain(update.direction);
        expect(Number.isNaN(Date.parse(update.timestamp as string))).toBe(false);
      }
    } finally {
      controller.abort();
    }
  });

  test('client reconnects after the stream drops', async ({ page, baseURL }) => {
    // Browse through a local proxy so the live SSE socket can be cut mid-stream.
    const proxy = await startStreamProxy(baseURL!);
    try {
      await page.goto(proxy.url);
      await expectConnected(page);
      const status = page.getByTestId('connection-status');

      proxy.dropStream();
      await expect(status).not.toHaveAttribute('data-status', 'connected', { timeout: 15_000 });
      expect(['reconnecting', 'disconnected']).toContain(await status.getAttribute('data-status'));

      // Let reconnects through: EventSource retries (retry: 1000) and the dot goes green again.
      proxy.restore();
      await expectConnected(page, 20_000);

      // Prices flow again after reconnecting.
      const cell = page.getByTestId('watchlist-price-AAPL');
      const first = await cell.textContent();
      await expect.poll(() => cell.textContent(), { timeout: 10_000 }).not.toBe(first);
    } finally {
      await proxy.close();
    }
  });
});
