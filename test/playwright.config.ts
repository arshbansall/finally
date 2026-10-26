import { defineConfig, devices } from '@playwright/test';

/**
 * FinAlly E2E suite.
 *
 * Local:  BASE_URL=http://localhost:8100 npx playwright test
 *         (app started with LLM_MOCK=true and a throwaway FINALLY_DB_PATH)
 * Docker: docker compose -f test/docker-compose.test.yml up --build --abort-on-container-exit
 *
 * The suite expects a fresh database. The `fresh-start` project runs first and checks the
 * pristine seed state; everything else depends on it and only asserts deltas relative to
 * state read from the API, using a distinct ticker per scenario.
 */
const BASE_URL = process.env.BASE_URL ?? 'http://localhost:8100';

const desktop = {
  ...devices['Desktop Chrome'],
  viewport: { width: 1600, height: 1000 },
};

export default defineConfig({
  testDir: './e2e',
  fullyParallel: false,
  workers: 1, // one shared portfolio per server: keep cash/position deltas deterministic
  retries: 0,
  forbidOnly: !!process.env.CI,
  timeout: 60_000,
  globalTimeout: 10 * 60_000, // never hang CI if the app stops responding
  expect: { timeout: 10_000 },
  reporter: [['list'], ['html', { open: 'never' }]],
  use: {
    baseURL: BASE_URL,
    trace: 'retain-on-failure',
    screenshot: 'only-on-failure',
    video: 'retain-on-failure',
  },
  projects: [
    {
      name: 'fresh-start',
      testMatch: /fresh-start\.spec\.ts/,
      use: desktop,
    },
    {
      name: 'e2e',
      testIgnore: /fresh-start\.spec\.ts/,
      dependencies: ['fresh-start'],
      use: desktop,
    },
  ],
});
