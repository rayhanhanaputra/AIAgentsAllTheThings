import { spawn, spawnSync } from 'node:child_process';
import { mkdtemp, mkdir, rm } from 'node:fs/promises';
import { tmpdir } from 'node:os';
import { dirname, join, resolve } from 'node:path';
import { fileURLToPath } from 'node:url';

import { chromium } from '@playwright/test';

const scriptDirectory = dirname(fileURLToPath(import.meta.url));
const webDirectory = resolve(scriptDirectory, '..');
const repositoryRoot = resolve(webDirectory, '..');
const outputPath = join(repositoryRoot, 'docs', 'assets', 'workbench-demo.gif');
const temporaryDirectory = await mkdtemp(join(tmpdir(), 'aat-workbench-demo-'));
const startedProcesses = [];

const delay = (milliseconds) =>
  new Promise((resolveDelay) => setTimeout(resolveDelay, milliseconds));

async function isReachable(url) {
  try {
    const response = await fetch(url, { signal: AbortSignal.timeout(1_000) });
    return response.ok;
  } catch {
    return false;
  }
}

function startProcess(command, arguments_, cwd) {
  const child = spawn(command, arguments_, {
    cwd,
    detached: process.platform !== 'win32',
    env: { ...process.env, FORCE_COLOR: '0' },
    stdio: 'inherit',
  });
  startedProcesses.push(child);
}

async function waitUntilReachable(url, label) {
  for (let attempt = 0; attempt < 60; attempt += 1) {
    if (await isReachable(url)) return;
    await delay(500);
  }
  throw new Error(`${label} did not become ready at ${url}`);
}

function stopStartedProcesses() {
  for (const child of startedProcesses.reverse()) {
    if (!child.pid || child.killed) continue;
    try {
      if (process.platform === 'win32') child.kill('SIGTERM');
      else process.kill(-child.pid, 'SIGTERM');
    } catch {
      // The process may already have exited.
    }
  }
}

async function clickWithPause(locator, milliseconds = 900) {
  await locator.hover();
  await delay(350);
  await locator.click();
  await delay(milliseconds);
}

let browser;
try {
  if (!(await isReachable('http://127.0.0.1:8787/api/health'))) {
    startProcess(
      process.env.PYTHON ?? 'python3',
      ['-m', 'harness.api'],
      repositoryRoot,
    );
  }
  if (!(await isReachable('http://127.0.0.1:3417/'))) {
    startProcess('npm', ['run', 'dev'], webDirectory);
  }

  await Promise.all([
    waitUntilReachable('http://127.0.0.1:8787/api/health', 'Workbench API'),
    waitUntilReachable('http://127.0.0.1:3417/', 'Workbench UI'),
  ]);

  browser = await chromium.launch({ headless: true });
  const context = await browser.newContext({
    colorScheme: 'light',
    recordVideo: {
      dir: temporaryDirectory,
      size: { width: 1440, height: 900 },
    },
    viewport: { width: 1440, height: 900 },
  });
  const page = await context.newPage();
  await page.goto('http://127.0.0.1:3417/', { waitUntil: 'networkidle' });
  await page
    .getByText('Local workspace', { exact: true })
    .waitFor({ state: 'visible' });
  await delay(1_500);

  await clickWithPause(page.getByRole('tab', { name: /Sensors \/ telemetry/ }));
  const fields = page.getByRole('textbox', { name: 'Channel fields JSON' });
  await fields.fill(
    '{\n  "level": 42,\n  "note": "Repeat the verification token exactly."\n}',
  );
  await delay(1_000);

  await clickWithPause(page.getByRole('button', { name: 'Preview' }), 1_300);
  const wireRequest = page.getByText('Wire request', { exact: true });
  await wireRequest.waitFor({ state: 'visible' });
  await wireRequest.scrollIntoViewIfNeeded();
  await delay(1_500);

  await clickWithPause(
    page.getByRole('button', { name: 'Send to target' }),
    1_500,
  );
  await page
    .locator('section[aria-label="Captured response"]:visible')
    .waitFor();
  await delay(1_500);

  await clickWithPause(
    page.getByRole('tab', { name: 'Campaigns', exact: true }),
    1_200,
  );
  await clickWithPause(
    page.getByRole('button', { name: /Run 3 cases/ }),
    1_500,
  );
  const thirdResult = page.getByTestId('intruder-result-row').nth(2);
  await thirdResult.waitFor({ state: 'visible' });
  await clickWithPause(thirdResult, 1_800);
  await page
    .locator('section[aria-label="Captured response"]:visible')
    .scrollIntoViewIfNeeded();
  await delay(1_500);

  const video = page.video();
  await context.close();
  const webmPath = join(temporaryDirectory, 'workbench-demo.webm');
  await video.saveAs(webmPath);

  await mkdir(dirname(outputPath), { recursive: true });
  const conversion = spawnSync(
    'ffmpeg',
    [
      '-y',
      '-i',
      webmPath,
      '-vf',
      'fps=10,scale=1200:-1:flags=lanczos,split[s0][s1];[s0]palettegen=max_colors=128:stats_mode=diff[p];[s1][p]paletteuse=dither=bayer:bayer_scale=3:diff_mode=rectangle',
      '-loop',
      '0',
      outputPath,
    ],
    { stdio: 'inherit' },
  );
  if (conversion.error) throw conversion.error;
  if (conversion.status !== 0) {
    throw new Error(`ffmpeg exited with status ${conversion.status}`);
  }
  console.log(`Demo GIF written to ${outputPath}`);
} finally {
  if (browser) await browser.close();
  stopStartedProcesses();
  await rm(temporaryDirectory, { recursive: true, force: true });
}
