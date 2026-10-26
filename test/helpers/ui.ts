import { expect, type Locator, type Page } from '@playwright/test';

/** "$10,000.00" / "-$5.25" / "10,000" -> number */
export function parseMoney(text: string | null): number {
  const cleaned = (text ?? '').replace(/[^0-9.\-]/g, '');
  const value = Number.parseFloat(cleaned);
  if (Number.isNaN(value)) throw new Error(`Not a number: ${JSON.stringify(text)}`);
  return value;
}

export async function readMoney(locator: Locator): Promise<number> {
  return parseMoney(await locator.textContent());
}

export async function expectConnected(page: Page, timeout = 15_000): Promise<void> {
  await expect(page.getByTestId('connection-status')).toHaveAttribute('data-status', 'connected', {
    timeout,
  });
}

/** Load the app and wait until the price stream is live. */
export async function openApp(page: Page): Promise<void> {
  await page.goto('/');
  await expect(page.getByTestId('watchlist')).toBeVisible();
  await expectConnected(page);
}

/** Poll a money-valued element until it is within `tolerance` of `expected`. */
export async function expectMoneyNear(
  locator: Locator,
  expected: number,
  tolerance = 0.01,
  timeout = 10_000,
): Promise<void> {
  await expect
    .poll(async () => Math.abs((await readMoney(locator).catch(() => Number.NaN)) - expected), {
      message: `expected ~${expected} (±${tolerance})`,
      timeout,
    })
    .toBeLessThanOrEqual(tolerance);
}

/** A cell inside `row` whose whole text is the given number (e.g. "3" or "3.00"). */
export function numberCell(row: Locator, value: number): Locator {
  const n = String(value).replace('.', '\\.');
  return row.getByText(new RegExp(`^\\s*${n}(\\.0+)?\\s*$`)).first();
}

/** Fill the trade bar and click buy/sell (no waiting; the UI may reject client-side). */
export async function submitTrade(
  page: Page,
  ticker: string,
  quantity: number,
  side: 'buy' | 'sell',
): Promise<void> {
  await page.getByTestId('trade-ticker-input').fill(ticker);
  await page.getByTestId('trade-quantity-input').fill(String(quantity));
  await page.getByTestId(side === 'buy' ? 'trade-buy-button' : 'trade-sell-button').click();
}

/** Submit a trade through the UI and return the POST /api/portfolio/trade response. */
export async function placeTrade(
  page: Page,
  ticker: string,
  quantity: number,
  side: 'buy' | 'sell',
) {
  const responsePromise = page.waitForResponse(
    (r) => r.url().endsWith('/api/portfolio/trade') && r.request().method() === 'POST',
  );
  await submitTrade(page, ticker, quantity, side);
  return responsePromise;
}

export async function sendChat(page: Page, message: string) {
  await page.getByTestId('chat-input').fill(message);
  const responsePromise = page.waitForResponse(
    (r) => r.url().endsWith('/api/chat') && r.request().method() === 'POST',
  );
  await page.getByTestId('chat-send-button').click();
  return responsePromise;
}
