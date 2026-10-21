import { test, expect } from '@playwright/test';
test('chat streams, diff approval survives reconnect, context, settings, and read-only share', async ({
  page,
  context,
}) => {
  const errors: string[] = [];
  page.on('pageerror', (e) => errors.push(e.message));
  await page.goto('/#token=browser-test');
  await expect(page.getByRole('heading', { name: 'What are we building?' })).toBeVisible();
  await page.getByRole('button', { name: 'Check setup', exact: true }).click();
  await expect(page.getByLabel('Setup results')).toContainText('Connection was not checked.');
  await expect(page.getByLabel('Setup results')).toContainText('Model profile');
  await expect(
    page.getByRole('button', { name: 'Check model connection', exact: true }),
  ).toBeInViewport();
  await page.screenshot({ path: 'test-results/setup-desktop.png', fullPage: true });
  const offlineReport = await page.request
    .post('/api/diagnostics', {
      headers: { origin: 'http://127.0.0.1:38765' },
      data: {},
    })
    .then((r) => r.json());
  await page.route('**/api/diagnostics', async (route) => {
    expect(route.request().postDataJSON().probe).toBe(true);
    await route.fulfill({
      json: {
        ...offlineReport,
        ok: false,
        probe_requested: true,
        checks: offlineReport.checks.map((c: any) =>
          c.id === 'connection'
            ? {
                ...c,
                status: 'error',
                detail: 'Fixture model server is offline.',
                remedy: 'Start the model server and check its endpoint.',
              }
            : c,
        ),
      },
    });
  });
  await page.getByRole('button', { name: 'Check model connection', exact: true }).click();
  await expect(page.getByLabel('Setup results')).toContainText('Fixture model server is offline.');
  await page.unroute('**/api/diagnostics');
  await page.getByRole('button', { name: 'Open model settings', exact: true }).click();
  await expect(page.getByRole('dialog')).toContainText('Models');
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.screenshot({ path: 'test-results/workspace-desktop.png', fullPage: true });
  await page
    .getByRole('textbox', { name: 'Message Smok' })
    .fill('Please edit hello.py from before to after.');
  await page.getByRole('button', { name: 'Send message', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Accept change', exact: true })).toBeVisible();
  await expect(page.getByLabel('Proposed changes').last()).toContainText('+after');
  await page.reload();
  await expect(page.getByRole('button', { name: 'Accept change', exact: true })).toBeVisible();
  const diffBox = await page.getByLabel('Proposed changes').last().boundingBox();
  const addedBox = await page.locator('.approval .diff .added').boundingBox();
  expect(addedBox!.y + addedBox!.height).toBeLessThanOrEqual(diffBox!.y + diffBox!.height);
  await page.screenshot({ path: 'test-results/approval-desktop.png', fullPage: true });
  await page.getByRole('button', { name: 'Always allow', exact: true }).click();
  await expect(page.getByText('The workspace is ready.', { exact: true }).last()).toBeVisible();
  await expect(page.getByRole('button', { name: 'Stop turn', exact: true })).toHaveCount(0);
  await page.getByRole('button', { name: 'Set run budget', exact: true }).click();
  await page.getByLabel('Turn time limit in seconds', { exact: true }).fill('180');
  await page.getByRole('button', { name: 'Set limits', exact: true }).click();
  await page.getByRole('button', { name: 'Set run budget', exact: true }).click();
  await expect(page.getByLabel('Turn time limit in seconds', { exact: true })).toHaveValue('180');
  await page.screenshot({ path: 'test-results/turn-limits.png', fullPage: true });
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.getByRole('textbox', { name: 'Pin file path' }).fill('hello.py');
  await page.getByRole('button', { name: 'Pin file', exact: true }).click();
  await expect(page.getByRole('button', { name: 'Drop hello.py', exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByRole('button', { name: 'Permissions', exact: true }).click();
  await expect(page.getByText('file_edit', { exact: true })).toBeVisible();
  await page.getByRole('button', { name: 'Models', exact: true }).click();
  await page.getByLabel('Prompt style', { exact: true }).first().selectOption('lean');
  await page.getByLabel('Reasoning effort', { exact: true }).first().selectOption('none');
  await page.getByLabel('Temperature', { exact: true }).first().fill('0');
  await page.getByLabel('Top-p', { exact: true }).first().fill('0.95');
  await page.getByLabel('Tool set', { exact: true }).first().selectOption('coding');
  await page.getByLabel('Edit format', { exact: true }).first().selectOption('exact');
  await page.screenshot({ path: 'test-results/settings-tuning.png', fullPage: true });
  await page.getByRole('button', { name: 'API keys', exact: true }).click();
  await page.getByLabel('OPENAI_API_KEY', { exact: true }).fill('browser-fixture-key');
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await expect(page.getByRole('dialog')).toHaveCount(0);
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await expect(page.getByLabel('Prompt style', { exact: true }).first()).toHaveValue('lean');
  await expect(page.getByLabel('Reasoning effort', { exact: true }).first()).toHaveValue('none');
  await expect(page.getByLabel('Temperature', { exact: true }).first()).toHaveValue('0');
  await expect(page.getByLabel('Top-p', { exact: true }).first()).toHaveValue('0.95');
  await expect(page.getByLabel('Tool set', { exact: true }).first()).toHaveValue('coding');
  await expect(page.getByLabel('Edit format', { exact: true }).first()).toHaveValue('exact');
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.getByRole('button', { name: 'Share session', exact: true }).click();
  await page.getByRole('button', { name: 'Preview transcript', exact: true }).click();
  await page.getByRole('button', { name: 'Create link for this transcript', exact: true }).click();
  const link = await page.locator('.created-link a').getAttribute('href');
  expect(link).toBeTruthy();
  const shared = await context.newPage();
  await shared.goto(link!);
  await expect(shared.getByText('READ ONLY', { exact: true })).toBeVisible();
  await expect(shared.getByRole('textbox')).toHaveCount(0);
  await expect(shared.getByText('The workspace is ready.', { exact: true }).last()).toBeVisible();
  await shared.close();
  await page.getByRole('button', { name: 'Revoke share', exact: true }).last().click();
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.getByRole('button', { name: 'Branch', exact: true }).first().click();
  await expect(page.locator('.session-heading h1')).toContainText('Branch');
  expect(errors).toEqual([]);
});
test('mobile layout, model forms, image input, and dictation compatibility', async ({ page }) => {
  await page.addInitScript(() => {
    (window as any).SpeechRecognition = class {
      onresult: any;
      onend: any;
      start() {
        setTimeout(() => {
          this.onresult?.({ results: [[{ transcript: 'Draft a small parser.' }]] });
          this.onend?.();
        }, 0);
      }
      stop() {
        this.onend?.();
      }
      abort() {}
    };
  });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/#token=browser-test');
  await page.getByRole('button', { name: 'Open sessions', exact: true }).click();
  await page.getByRole('button', { name: 'New session', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'What are we building?' })).toBeVisible();
  await page.screenshot({ path: 'test-results/workspace-mobile.png', fullPage: true });
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Check setup', exact: true }).click();
  await expect(page.getByLabel('Setup results')).toContainText('Connection was not checked.');
  await page.screenshot({ path: 'test-results/setup-mobile.png', fullPage: true });
  await expect(
    page.getByRole('button', { name: 'Check model connection', exact: true }),
  ).toBeInViewport();
  expect(await page.evaluate(() => document.documentElement.scrollWidth <= innerWidth)).toBe(true);
  await page.getByRole('button', { name: 'Close dialog', exact: true }).click();
  await page.getByRole('button', { name: 'Open sessions', exact: true }).click();
  await page.getByRole('button', { name: 'Settings', exact: true }).click();
  await page.getByLabel('Vision input', { exact: true }).first().check();
  await page.getByRole('button', { name: 'Save settings', exact: true }).click();
  await page.getByRole('button', { name: 'Close sessions', exact: true }).click();
  await page.locator('input[type=file]').setInputFiles('../assets/dragon_mascot_512.png');
  await expect(page.locator('.attachments img')).toBeVisible();
  await page.getByRole('button', { name: 'Remove dragon_mascot_512.png', exact: true }).click();
  await page.getByRole('button', { name: 'Voice input', exact: true }).click();
  await expect(
    page.getByText('Your browser may use an online speech service', { exact: false }),
  ).toBeVisible();
  await page.getByRole('button', { name: 'Start dictation', exact: true }).click();
  await expect(page.getByRole('textbox', { name: 'Message Smok' })).toHaveValue(
    'Draft a small parser.',
  );
  await expect(page.getByRole('button', { name: 'Stop turn', exact: true })).toHaveCount(0);
});
