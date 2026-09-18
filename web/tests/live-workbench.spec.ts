import { expect, test } from '@playwright/test';

test.skip(
  process.env.AAT_LIVE_E2E !== '1',
  'requires the local Workbench API and dummy targets',
);

test('browser to mapper to real HTTP connector captures the response', async ({
  page,
  request,
}) => {
  const created = await request.post('http://127.0.0.1:8787/api/targets', {
    data: {
      name: 'Browser E2E mapped target',
      environment: 'staging',
      connector: 'http',
      endpoint: 'http://127.0.0.1:9101/agent',
      request_template: '"{{mapped}}"',
      response_path: 'answer',
      evidence: {
        response_markers: ['AAT-E2E-OK'],
        forbidden_tools: [],
      },
      mapper_enabled: true,
      mapper_endpoint: 'http://127.0.0.1:9101/v1/chat/completions',
      mapper_model: 'dummy-mapper',
      mapper_api_key_env: 'AAT_DUMMY_MAPPER_KEY',
      mapper_instructions: 'Return command and parameters.',
      mapper_required_keys: ['command', 'parameters'],
    },
  });
  expect(created.ok()).toBe(true);
  const target = (await created.json()) as { id: string };

  try {
    await page.goto('/');
    await expect(
      page.getByText('Local workspace', { exact: true }),
    ).toHaveAttribute('data-api-status', 'online');
    const workbench = page.getByRole('tabpanel', { name: 'Workbench' });
    await workbench.getByLabel('Target agent').selectOption(target.id);
    await workbench.getByRole('button', { name: 'Send to target' }).click();
    await expect(workbench.getByText(/AAT-E2E-OK via http/)).toBeVisible();
    await expect(
      workbench.getByText('Canary exposed', { exact: true }),
    ).toBeVisible();
    await workbench.getByRole('tab', { name: 'Analysis' }).click();
    await expect(
      workbench.getByText(/Forbidden response marker observed/),
    ).toBeVisible();
  } finally {
    await request.delete(`http://127.0.0.1:8787/api/targets/${target.id}`);
  }
});
