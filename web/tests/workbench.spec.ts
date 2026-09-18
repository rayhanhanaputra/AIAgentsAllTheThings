import { expect, test } from '@playwright/test';

function sessionResult({
  runId,
  mode,
  script,
  response,
}: {
  runId: string;
  mode: 'repeater' | 'intruder' | 'channel' | 'workbench' | 'campaign';
  script: string;
  response: string;
}) {
  return {
    run_id: runId,
    mode,
    state: 'completed',
    provider: 'simulated',
    script,
    response_text: response,
    canary: `CANARY-${runId}`,
    duration_ms: runId.endsWith('2') ? 42 : 21,
    events: [],
    analysis: {
      verdict: 'no_violation_observed',
      canary_matches: 0,
      evidence: ['No canary exposure observed.'],
      llm_review: null,
    },
  };
}

const intruderCases = [
  {
    case_index: 0,
    payload: 'first payload',
    result: sessionResult({
      runId: 'intruder-run-1',
      mode: 'campaign',
      script: '{"prompt":"first payload"}',
      response: 'First intruder response',
    }),
  },
  {
    case_index: 7,
    payload: 'second payload',
    result: sessionResult({
      runId: 'intruder-run-2',
      mode: 'campaign',
      script: '{"prompt":"second payload"}',
      response: 'Second intruder response',
    }),
  },
];

const historyRuns = [
  sessionResult({
    runId: 'history-run-1',
    mode: 'workbench',
    script: 'first history input',
    response: 'First history response',
  }),
  sessionResult({
    runId: 'history-run-2',
    mode: 'campaign',
    script: 'second history input',
    response: 'Second history response',
  }),
];

test.beforeEach(async ({ page }) => {
  const targets: Array<Record<string, unknown>> = [
    {
      id: 'local-simulator',
      name: 'Local Simulator',
      environment: 'simulation',
      connector: 'simulator',
      enabled: true,
      endpoint: null,
      method: 'POST',
      headers: {},
      secret_headers: {},
      request_template: '{"input":"{{input}}"}',
      response_path: null,
      actions_path: null,
      host: null,
      port: null,
      tcp_raw: false,
      timeout_seconds: 20,
      evidence: { response_markers: [], forbidden_tools: [] },
      created_at: '2026-09-18T00:00:00Z',
      updated_at: '2026-09-18T00:00:00Z',
    },
    {
      id: 'production-agent',
      name: 'Production Agent',
      environment: 'production',
      connector: 'http',
      enabled: true,
      endpoint: 'https://agent.example.com/api/chat',
      method: 'POST',
      headers: {},
      secret_headers: { Authorization: 'PROD_AGENT_AUTH' },
      request_template: '{"input":"{{input}}"}',
      response_path: 'answer',
      actions_path: 'actions',
      host: null,
      port: null,
      tcp_raw: false,
      timeout_seconds: 20,
      evidence: {
        response_markers: ['LEAK-MARKER'],
        forbidden_tools: ['open_valve'],
      },
      created_at: '2026-09-18T00:00:00Z',
      updated_at: '2026-09-18T00:00:00Z',
    },
  ];
  // Layout tests use local fixtures and never send assessment requests.
  await page.route('http://127.0.0.1:8787/api/**', async (route) => {
    if (route.request().url().endsWith('/health')) {
      await route.fulfill({ json: { status: 'ok' } });
    } else if (
      route.request().url().endsWith('/runs') &&
      route.request().method() === 'GET'
    ) {
      await route.fulfill({ json: { runs: historyRuns } });
    } else if (
      route.request().url().endsWith('/targets') &&
      route.request().method() === 'GET'
    ) {
      await route.fulfill({ json: { targets } });
    } else if (
      route.request().url().endsWith('/targets') &&
      route.request().method() === 'POST'
    ) {
      const input = route.request().postDataJSON() as Record<string, unknown>;
      const target = {
        ...targets[0],
        ...input,
        id: 'created-target',
        created_at: '2026-09-18T00:01:00Z',
        updated_at: '2026-09-18T00:01:00Z',
      };
      targets.unshift(target);
      await route.fulfill({ status: 201, json: target });
    } else if (route.request().url().endsWith('/campaigns/runs')) {
      await route.fulfill({
        json: {
          case_count: intruderCases.length,
          confirmed_violations: 0,
          effective_concurrency: 2,
          cases: intruderCases,
        },
      });
    } else if (route.request().url().endsWith('/preview')) {
      const request = route.request().postDataJSON() as {
        adapter: string;
        fields: Record<string, unknown>;
      };
      await route.fulfill({
        json: {
          target: targets[0],
          message: {
            msg_id: 'channel-message-1',
            topic: `workbench/${request.adapter}`,
            body:
              request.adapter === 'morse-blink'
                ? {
                    channel: 'relay-indicator',
                    encoding: 'morse',
                    morse: '.-. . .--. . .- - / - --- -.- . -.',
                    blink_units: [['on', 1]],
                  }
                : request.fields,
          },
          wire_request: {
            provider: 'simulated',
            input: JSON.stringify(request.fields),
          },
        },
      });
    } else if (route.request().url().endsWith('/workbench/runs')) {
      const request = route.request().postDataJSON() as {
        adapter: string;
        fields: Record<string, unknown>;
      };
      await route.fulfill({
        json: {
          ...sessionResult({
            runId: 'workbench-run-1',
            mode: 'workbench',
            script: JSON.stringify(request.fields, null, 2),
            response: 'Target input captured',
          }),
          metadata: {
            target: targets[0],
            channel: {
              adapter: request.adapter,
              message_id: 'channel-message-1',
              topic: `workbench/${request.adapter}`,
              body: request.fields,
            },
            exchange: { wire_request: { provider: 'simulated' }, actions: [] },
          },
        },
      });
    } else {
      await route.abort();
    }
  });
});

for (const width of [1440, 1024, 768, 390]) {
  test(`navigation stays above the workspace at ${width}px`, async ({
    page,
  }, testInfo) => {
    await page.setViewportSize({ width, height: 900 });
    await page.goto('/');
    await expect(
      page.getByText('Local workspace', { exact: true }),
    ).toHaveAttribute('data-api-status', 'online');
    await expect(page).toHaveTitle('AIAgentsAllTheThings');
    await expect(page.locator('.brand-mark img')).toHaveAttribute(
      'src',
      /logo-aiagentsallthethings\.png/,
    );
    await expect(
      page.getByRole('tab', { name: 'Workbench', exact: true }),
    ).toBeVisible();
    const nav = page.locator('.tool-navigation');
    const workspace = page.locator('.channels-workspace');
    await expect(page.locator('.workbench-tabs')).toHaveCSS(
      'flex-direction',
      'column',
    );
    await expect(page.locator('.response-tabs').first()).toHaveCSS(
      'flex-direction',
      'column',
    );
    const navRect = await nav.boundingBox();
    const requestRect = await workspace.boundingBox();
    expect(navRect).not.toBeNull();
    expect(requestRect).not.toBeNull();
    expect(navRect!.height).toBeLessThanOrEqual(60);
    expect(requestRect!.y).toBeGreaterThanOrEqual(
      navRect!.y + navRect!.height - 1,
    );
    expect(
      await page.evaluate(
        () => document.documentElement.scrollWidth <= window.innerWidth,
      ),
    ).toBe(true);
    await expect(page.locator('body')).not.toHaveCSS(
      'font-family',
      /Times New Roman/,
    );
    await page.screenshot({
      path: testInfo.outputPath(`workspace-${width}.png`),
      fullPage: true,
    });
  });
}

test('each tool uses one contiguous workspace surface', async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');

  const tools = [
    {
      tab: 'Workbench',
      workspace: '.channels-workspace',
      panes: ['.channel-picker', '.channel-config', '.channel-response'],
    },
    {
      tab: 'Campaigns',
      workspace: '.intruder-workspace',
      panes: ['.intruder-config', '.intruder-workspace > .results-pane'],
    },
    {
      tab: 'Targets',
      workspace: '.targets-workspace',
      panes: ['.target-list-pane', '.target-editor'],
    },
    {
      tab: 'History',
      workspace: '.history-workspace',
      panes: [
        '.history-workspace > .results-pane',
        '.history-workspace > .work-pane',
      ],
    },
  ];

  for (const tool of tools) {
    await page.getByRole('tab', { name: tool.tab, exact: true }).click();
    const workspace = page.locator(tool.workspace);
    await expect(workspace).toBeVisible();
    await expect(workspace).toHaveCSS('column-gap', '0px');
    await expect(workspace).toHaveCSS('border-top-style', 'solid');
    await expect(workspace).toHaveCSS('border-radius', '0px');
    await expect(workspace).toHaveCSS('margin-left', '0px');

    const boxes = await Promise.all(
      tool.panes.map(async (selector) => {
        const pane = page.locator(selector);
        await expect(pane).toHaveCSS('border-radius', '0px');
        return pane.boundingBox();
      }),
    );
    boxes.forEach((box) => expect(box).not.toBeNull());
    for (let index = 1; index < boxes.length; index += 1) {
      const previous = boxes[index - 1]!;
      const current = boxes[index]!;
      expect(
        Math.abs(previous.x + previous.width - current.x),
      ).toBeLessThanOrEqual(1);
    }
  }
});

test('all input channel families are inside the workbench and stay in the viewport', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await expect(
    page.getByRole('heading', { name: 'Workbench', exact: true }),
  ).toBeVisible();
  await expect(page.getByText('8 / 8 ready', { exact: true })).toBeVisible();
  await expect(page.getByRole('tab', { name: /Text \/ chat/ })).toBeVisible();
  await expect(
    page.getByRole('tab', { name: /RF \/ device messages/ }),
  ).toBeVisible();
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath('input-channels-mobile.png'),
    fullPage: true,
  });
});

test('a channel can be previewed, delivered to a target, and inspected', async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await page.getByRole('tab', { name: /Binary \/ Morse/ }).click();
  const workbench = page.getByRole('tabpanel', { name: 'Workbench' });
  await workbench.getByLabel('Input adapter').selectOption('morse-blink');
  await page.getByRole('button', { name: 'Send to target' }).click();

  await expect(page.getByText('Agent input', { exact: true })).toBeVisible();
  await expect(page.getByText('Wire request', { exact: true })).toBeVisible();
  await expect(page.locator('.encoded-message').first()).toContainText('morse');
  await expect(page.locator('.channel-response')).toContainText(
    'Target input captured',
  );
});

test('target agents can be configured without sending secret values', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await page.getByRole('tab', { name: 'Targets', exact: true }).click();
  await page
    .getByRole('textbox', { name: 'Name', exact: true })
    .fill('Production support agent');
  await page.locator('#target-environment').selectOption('production');
  await page.locator('#target-auth-env').fill('PROD_AGENT_AUTH');
  await page.getByRole('button', { name: 'Create target' }).click();

  await expect(
    page.getByRole('button', { name: /Production support agent/ }),
  ).toBeVisible();
  await expect(
    page.getByText(/Secret values stay in server environment/),
  ).toBeVisible();
});

test('production workbench requires explicit authorization acknowledgement', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  const workbench = page.getByRole('tabpanel', { name: 'Workbench' });
  await workbench.getByLabel('Target agent').selectOption('production-agent');

  const send = workbench.getByRole('button', { name: 'Send to target' });
  await expect(send).toBeDisabled();
  await workbench
    .getByRole('checkbox', {
      name: /I confirm this production or hardware target is in scope/,
    })
    .check();
  await expect(send).toBeEnabled();
});

test('an LLM input mapper can be configured using an environment reference', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await page.getByRole('tab', { name: 'Targets', exact: true }).click();
  await page.getByRole('checkbox', { name: /Use an LLM input mapper/ }).check();
  await page
    .getByLabel('Mapper API URL')
    .fill('http://127.0.0.1:9101/v1/chat/completions');
  await page.getByLabel('Mapper model').fill('dummy-mapper');
  await page
    .getByLabel('API key environment variable')
    .fill('aat_dummy_mapper_key');
  await page
    .getByLabel('Required target format')
    .fill('Return command and parameters.');
  await page.getByLabel('Required output keys').fill('command\nparameters');
  await page.getByLabel('Request template').fill('"{{mapped}}"');

  await expect(page.getByLabel('API key environment variable')).toHaveValue(
    'AAT_DUMMY_MAPPER_KEY',
  );
  await expect(page.getByText(/Mapping fails closed/)).toBeVisible();
});

test('an LLM response mapper preserves raw evidence and uses an environment reference', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await page.getByRole('tab', { name: 'Targets', exact: true }).click();
  await page
    .getByRole('checkbox', {
      name: /Normalize target responses with an LLM mapper/,
    })
    .check();
  await page
    .getByLabel('Response mapper API URL')
    .fill('http://127.0.0.1:9101/v1/chat/completions');
  await page.getByLabel('Response mapper model').fill('dummy-response-mapper');
  await page
    .getByLabel('API key environment variable')
    .fill('aat_dummy_response_mapper_key');
  await page
    .getByLabel('Response normalization guidance')
    .fill('Extract visible text and observed tool actions.');

  await expect(page.getByLabel('API key environment variable')).toHaveValue(
    'AAT_DUMMY_RESPONSE_MAPPER_KEY',
  );
  await expect(
    page.getByText(/Raw evidence is always preserved/),
  ).toBeVisible();
});

test('channel drafts survive changing tools and dark layout keeps its geometry', async ({
  page,
}, testInfo) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  const fields = page.getByRole('textbox', { name: 'Channel fields JSON' });
  await fields.fill('{"prompt":"A harmless test draft."}');
  await page.getByRole('tab', { name: 'Campaigns', exact: true }).click();
  await expect(page.getByRole('heading', { name: 'Campaigns' })).toBeVisible();
  await page.getByRole('tab', { name: 'Workbench', exact: true }).click();
  await expect(fields).toHaveValue('{"prompt":"A harmless test draft."}');
  await page.getByRole('button', { name: 'Switch to dark theme' }).click();
  await expect(page.locator('html')).toHaveClass('dark');
  await expect(fields).toHaveCSS('background-color', 'rgb(34, 36, 41)');
  await expect(fields).toHaveCSS('color', 'rgb(228, 229, 232)');
  await expect(page.locator('.workbench-tabs')).toHaveCSS(
    'flex-direction',
    'column',
  );
  expect(
    await page.evaluate(
      () => document.documentElement.scrollWidth <= window.innerWidth,
    ),
  ).toBe(true);
  await page.screenshot({
    path: testInfo.outputPath('workspace-dark.png'),
    fullPage: true,
  });
});

test('selecting any campaign result row updates the captured response', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await page.getByRole('tab', { name: 'Campaigns', exact: true }).click();
  await page.getByRole('button', { name: /Run 3 cases/ }).click();

  const responses = page.getByLabel('Captured response');
  await expect(responses.getByText('First intruder response')).toBeVisible();

  const secondRow = page.getByTestId('intruder-result-row').nth(1);
  await secondRow.click({ position: { x: 220, y: 16 } });
  const exchange = responses.locator('.transcript.is-split');
  await expect(exchange).toHaveCSS('grid-template-columns', /\d+px \d+px/);
  await expect(
    responses.getByText('{"prompt":"second payload"}'),
  ).toBeVisible();
  await expect(responses.getByText('Second intruder response')).toBeVisible();
  await expect(secondRow).toHaveAttribute('aria-pressed', 'true');
});

test('selecting any history row updates the captured response', async ({
  page,
}) => {
  await page.goto('/');
  await expect(
    page.getByText('Local workspace', { exact: true }),
  ).toHaveAttribute('data-api-status', 'online');
  await page.getByRole('tab', { name: 'History', exact: true }).click();

  const responses = page.getByLabel('Captured response');
  await expect(responses.getByText('First history response')).toBeVisible();

  const secondRow = page.getByTestId('history-run-row').nth(1);
  await secondRow.click({ position: { x: 180, y: 16 } });
  await expect(responses.getByText('Second history response')).toBeVisible();
  await expect(secondRow).toHaveAttribute('aria-pressed', 'true');
});
