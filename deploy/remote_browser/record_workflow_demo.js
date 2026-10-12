const fs = require('fs');
const { chromium } = require('playwright');

const workflowId = process.env.DEMO_WORKFLOW_ID || process.argv[2];
const demoName = process.env.DEMO_NAME || process.argv[3] || workflowId || 'workflow-demo';
const cdpUrl = process.env.TRAFFICWM_CDP_URL || 'http://127.0.0.1:9222';
const launchUrl = process.env.TRAFFICWM_URL || 'http://host.docker.internal:8890/?view=workflow';
const outputPath = process.env.DEMO_RESULT_PATH || `/tmp/${demoName}.json`;
const targetSeconds = Number(process.env.DEMO_TARGET_SECONDS || 60);
const maxWaitSeconds = Number(process.env.DEMO_MAX_WAIT_SECONDS || 300);
const layoutSequence = String(process.env.DEMO_LAYOUT_SEQUENCE || 'equal')
  .split(',')
  .map(value => value.trim())
  .filter(value => ['traffic-main', 'equal', 'video-main'].includes(value));

if (!workflowId) throw new Error('workflow id is required');

const sleep = (milliseconds) => new Promise(resolve => setTimeout(resolve, milliseconds));
const nowIso = () => new Date().toISOString();

function log(message, details = undefined) {
  const suffix = details === undefined ? '' : ` ${JSON.stringify(details)}`;
  process.stdout.write(`[${nowIso()}] ${message}${suffix}\n`);
}

async function dismissModal(page) {
  const modal = page.locator('.modal.show');
  if (!await modal.count()) return;
  const close = modal.locator('[data-bs-dismiss="modal"], .btn-close').first();
  if (await close.count()) await close.click().catch(() => {});
  await sleep(400);
}

async function showWorkflowSection(page, target, pauseMs) {
  const button = page.locator(`[data-workflow-target="${target}"]`);
  await button.scrollIntoViewIfNeeded();
  await button.click();
  await sleep(pauseMs);
}

async function experimentStatus(page, experimentId) {
  return page.evaluate(async (id) => {
    try {
      const controller = new AbortController();
      const timeout = window.setTimeout(() => controller.abort(), 5000);
      const [experimentResponse, artifactResponse] = await Promise.all([
        fetch(
          `/api/v1/experiments?experiment_id=${encodeURIComponent(id)}`,
          { cache: 'no-store', signal: controller.signal },
        ),
        fetch(
          `/api/v1/artifacts?experiment_id=${encodeURIComponent(id)}&compact=1`,
          { cache: 'no-store', signal: controller.signal },
        ),
      ]);
      window.clearTimeout(timeout);
      if (!experimentResponse.ok) {
        return {
          ok: false,
          experiment_http_status: experimentResponse.status,
        };
      }
      const experimentPayload = await experimentResponse.json();
      const artifactPayload = artifactResponse.ok ? await artifactResponse.json() : {};
      return {
        ok: true,
        ...(experimentPayload.experiment || {}),
        world_generation: artifactPayload.world_generation
          || experimentPayload.experiment?.world_generation
          || {},
        live_preview: artifactPayload.live_preview || {},
      };
    } catch (error) {
      return { ok: false, error: String(error) };
    }
  }, experimentId);
}

async function showViewerState(page, mode, pauseMs = 800) {
  const selector = page.locator('#viewerLayoutSelect');
  if (await selector.count()) {
    await selector.selectOption(mode).catch(() => {});
    await sleep(pauseMs);
  }
}

async function main() {
  const result = {
    demo_name: demoName,
    workflow_id: workflowId,
    target_seconds: targetSeconds,
    started_at: nowIso(),
    experiment_id: '',
    samples: [],
  };

  const browser = await chromium.connectOverCDP(cdpUrl);
  const contexts = browser.contexts();
  const context = contexts[0];
  if (!context) throw new Error('the visible Chromium instance has no browser context');
  let pages = context.pages();
  const page = pages[0] || await context.newPage();
  page.on('dialog', dialog => dialog.accept().catch(() => {}));

  const cacheBustedLaunchUrl = `${launchUrl}${launchUrl.includes('?') ? '&' : '?'}recording_run=${Date.now()}`;
  log('opening workflow page', { workflowId, launchUrl: cacheBustedLaunchUrl });
  await page.goto(cacheBustedLaunchUrl, { waitUntil: 'domcontentloaded', timeout: 60000 });
  await page.waitForSelector('#savedWorkflowSelect', { state: 'visible', timeout: 60000 });
  await page.evaluate(() => {
    if (typeof setPlatformSidebarCollapsed === 'function') setPlatformSidebarCollapsed(true);
  });
  const expectedWorkflow = await page.evaluate(async (id) => {
    if (typeof loadWorkflows !== 'function' || typeof loadStandardScenarios !== 'function') {
      throw new Error('workflow frontend services are not initialized');
    }
    await Promise.all([loadWorkflows(), loadStandardScenarios()]);
    const response = await fetch('/api/v1/workflows', { cache: 'no-store' });
    if (!response.ok) throw new Error(`workflow API returned HTTP ${response.status}`);
    const payload = await response.json();
    const workflows = Array.isArray(payload.workflows) ? payload.workflows : [];
    localStorage.setItem('denseworld-drive.workflows.v1', JSON.stringify(workflows));
    return workflows.find(workflow => workflow.id === id) || null;
  }, workflowId);
  if (!expectedWorkflow) throw new Error(`workflow ${workflowId} does not exist in the manager store`);
  const expectedScenario = await page.evaluate(async (scenarioId) => {
    const response = await fetch('/api/v1/data/standard-scenarios', { cache: 'no-store' });
    if (!response.ok) return null;
    const payload = await response.json();
    return (payload.records || []).find(record => record.library_id === scenarioId) || null;
  }, expectedWorkflow.scenario_id);
  await page.waitForFunction(
    id => [...document.querySelectorAll('#savedWorkflowSelect option')].some(option => option.value === id),
    workflowId,
    { timeout: 60000 },
  );

  await page.selectOption('#savedWorkflowSelect', workflowId);
  await page.locator('#loadWorkflowBtn').click();
  await page.waitForFunction(id => document.querySelector('#workflowIdBadge')?.textContent?.includes(id), workflowId);
  await page.waitForFunction(expected => {
    const selectedScenario = document.querySelector('[data-standard-scenario].selected')?.dataset?.standardScenario || '';
    return document.querySelector('#workflowTrafficModelSelect')?.value === expected.traffic_model
      && document.querySelector('#workflowAvModelSelect')?.value === expected.av_model
      && Number(document.querySelector('#workflowDurationInput')?.value) === Number(expected.duration_seconds)
      && selectedScenario === expected.scenario_id;
  }, expectedWorkflow, { timeout: 30000 });
  await sleep(1800);

  const loaded = await page.evaluate(() => ({
    id: document.querySelector('#workflowIdBadge')?.textContent?.trim(),
    name: document.querySelector('#workflowNameInput')?.value,
    duration_seconds: Number(document.querySelector('#workflowDurationInput')?.value),
    traffic_model: document.querySelector('#workflowTrafficModelSelect')?.value,
    av_model: document.querySelector('#workflowAvModelSelect')?.value,
    scenario: document.querySelector('[data-standard-scenario].selected')?.dataset?.standardScenario || '',
    dreams_enabled: document.querySelector('#workflowDreamsToggle')?.checked,
    existing_seed: document.querySelector('#workflowExistingSeedToggle')?.checked,
    seed_backend: document.querySelector('#workflowSeedBackendSelect')?.value,
    transfer_seed: Number(
      readWorkflows().find(workflow => workflow.id === selectedWorkflowId)?.world_transfer_seed ?? 0,
    ),
  }));
  result.workflow = loaded;
  result.expected_workflow = {
    id: expectedWorkflow.id,
    name: expectedWorkflow.name,
    scenario_id: expectedWorkflow.scenario_id,
    traffic_model: expectedWorkflow.traffic_model,
    av_model: expectedWorkflow.av_model,
    duration_seconds: expectedWorkflow.duration_seconds,
    world_seed_backend: expectedWorkflow.world_seed_backend,
    world_transfer_seed: expectedWorkflow.world_transfer_seed,
  };
  result.expected_scenario = expectedScenario ? {
    library_id: expectedScenario.library_id,
    library_name: expectedScenario.library_name,
    backend_model: expectedScenario.backend_model,
    seed_ego_id: expectedScenario.seed_ego_id,
  } : null;
  log('workflow loaded', loaded);
  if (loaded.duration_seconds !== targetSeconds) {
    throw new Error(`workflow duration is ${loaded.duration_seconds}s, expected ${targetSeconds}s`);
  }
  if (!loaded.dreams_enabled) throw new Error('OmniDreams is not enabled in the selected workflow');
  if (
    loaded.id !== expectedWorkflow.id
    || loaded.traffic_model !== expectedWorkflow.traffic_model
    || loaded.av_model !== expectedWorkflow.av_model
    || loaded.scenario !== expectedWorkflow.scenario_id
    || loaded.seed_backend !== (expectedWorkflow.world_seed_backend || 'transfer1')
    || loaded.transfer_seed !== Number(expectedWorkflow.world_transfer_seed ?? 0)
  ) {
    throw new Error(`loaded workflow fields do not match manager record: ${JSON.stringify(loaded)}`);
  }

  await showWorkflowSection(page, 'workflowSubject', 2800);
  await showWorkflowSection(page, 'workflowScenario', 4200);
  await showWorkflowSection(page, 'workflowEvaluation', 2600);
  await showWorkflowSection(page, 'workflowParameters', 4200);
  await showWorkflowSection(page, 'workflowMultimodal', 4200);

  await page.locator('#saveWorkflowBtn').click();
  await sleep(2600);
  await showWorkflowSection(page, 'workflowLaunch', 3200);

  log('launching experiment from visible frontend');
  await page.locator('#workflowLaunchBtn').click();
  await page.waitForURL(url => url.searchParams.has('experiment_id'), { timeout: 120000 });
  const experimentId = new URL(page.url()).searchParams.get('experiment_id');
  result.experiment_id = experimentId;
  result.viewer_opened_at = nowIso();
  log('experiment viewer opened', { experimentId, url: page.url() });

  await page.waitForSelector('#workspace', { state: 'visible', timeout: 60000 });
  await dismissModal(page);
  await page.evaluate(() => {
    if (typeof setPlatformSidebarCollapsed === 'function') setPlatformSidebarCollapsed(true);
    if (typeof setMetricsPanelCollapsed === 'function') setMetricsPanelCollapsed(false);
    if (typeof setViewerSplitRatio === 'function') setViewerSplitRatio(1 / 3, true);
  });
  await showViewerState(page, 'equal', 1500);
  const followButton = page.locator('#followEgoBtn');
  if (await followButton.count()) await followButton.click().catch(() => {});

  const monitorStarted = Date.now();
  let lastLayoutSlot = -1;
  let finalStatus = null;
  let terminalSince = 0;
  let avSelectionConfirmed = false;
  let egoFocusConfirmed = false;
  while ((Date.now() - monitorStarted) / 1000 < maxWaitSeconds) {
    await dismissModal(page);
    const elapsed = (Date.now() - monitorStarted) / 1000;
    const slot = Math.floor(elapsed / 12) % Math.max(layoutSequence.length, 1);
    if (slot !== lastLayoutSlot) {
      lastLayoutSlot = slot;
      await showViewerState(page, layoutSequence[slot] || 'equal');
      const liveTab = page.locator('#tab-live');
      if (await liveTab.count()) await liveTab.click().catch(() => {});
    }

    const status = await experimentStatus(page, experimentId);
    if (!egoFocusConfirmed && Number(status.sim_time || 0) > 0) {
      egoFocusConfirmed = await page.evaluate(() => {
        if (typeof activeEgoId !== 'function' || !activeEgoId()) return false;
        followEgoVehicle();
        return Boolean(selectedVehicleId);
      }).catch(() => false);
      if (egoFocusConfirmed) log('focused the live traffic view around the ego vehicle');
    }
    if (
      status.waiting_for_av_selection
      && !avSelectionConfirmed
      && expectedScenario?.seed_ego_id
    ) {
      const seedEgoId = String(expectedScenario.seed_ego_id);
      await page.evaluate((vehicleId) => {
        selectedVehicleId = vehicleId;
        updateSelectedVehiclePanel();
        requestDrawFrame();
      }, seedEgoId);
      const confirmButton = page.locator('#confirmSelectAvBtn');
      if (await confirmButton.count() && !await confirmButton.isDisabled()) {
        await confirmButton.click();
        avSelectionConfirmed = true;
        result.av_selection = { vehicle_id: seedEgoId, confirmed_at: nowIso() };
        log('selected the scenario ego vehicle in the visible frontend', result.av_selection);
        await sleep(1000);
      }
    }
    const generation = status.world_generation || status.worldGeneration || {};
    const payload = generation.payload || {};
    const progress = payload.omnidreams_progress || status.omnidreams_progress || {};
    const livePreview = status.live_preview || {};
    const frameProgress = String(generation.message || '').match(/frame\s+(\d+)\/(\d+)/i);
    const messageVideoTime = frameProgress ? Number(frameProgress[1]) / 30 : null;
    const generatedVideoTime = Number(
      progress.generated_video_time
      ?? payload.generated_video_time
      ?? livePreview.generated_video_time
      ?? messageVideoTime
      ?? (Number(generation.progress || 0) * targetSeconds),
    );
    const playbackVideoTime = Number(
      livePreview.playback_time
      ?? status.world_video_time
      ?? 0,
    );
    const sample = {
      wall_seconds: Number(elapsed.toFixed(2)),
      ok: status.ok,
      run_state: status.run_state,
      sim_time: Number(status.sim_time ?? 0),
      vehicles: Number(status.vehicles ?? status.motorized_count ?? 0),
      world_stage: generation.stage || status.world_stage || '',
      world_run_state: generation.run_state || status.world_run_state || '',
      generated_video_time: generatedVideoTime,
      video_time: playbackVideoTime,
      preview_terminal: livePreview.terminal === true,
      preview_playback_index: Number(livePreview.playback_index ?? -1),
      preview_newest_index: Number(livePreview.newest_index ?? -1),
    };
    result.samples.push(sample);
    finalStatus = sample;
    if (result.samples.length === 1 || result.samples.length % 5 === 0) log('runtime sample', sample);

    const trafficTerminal = ['completed', 'error', 'stopped', 'interrupted'].includes(sample.run_state);
    const worldTerminal = ['completed', 'error', 'stopped', 'interrupted'].includes(sample.world_run_state);
    const failedTerminal = ['error', 'stopped', 'interrupted'].includes(sample.run_state)
      || ['error', 'stopped', 'interrupted'].includes(sample.world_run_state);
    const generatedComplete = sample.generated_video_time >= targetSeconds - 0.2;
    const previewIndexComplete = sample.preview_terminal
      && sample.preview_playback_index >= 0
      && sample.preview_playback_index >= sample.preview_newest_index;
    const playbackComplete = sample.video_time >= targetSeconds - 0.2 || previewIndexComplete;
    if (failedTerminal || (trafficTerminal && worldTerminal && generatedComplete && playbackComplete)) {
      if (!terminalSince) terminalSince = Date.now();
      if (Date.now() - terminalSince > 5000) break;
    } else {
      terminalSince = 0;
    }
    await sleep(1000);
  }

  await dismissModal(page);
  await showViewerState(page, 'equal', 2000);
  const video = page.locator('#worldVideoPlayer');
  if (await video.count() && await video.isVisible().catch(() => false)) {
    log('holding the completed split view for the recording');
    await sleep(6000);
  }
  await showViewerState(page, 'equal', 1500);

  result.finished_at = nowIso();
  result.final_status = finalStatus;
  result.page_url = page.url();
  result.success = Boolean(
    finalStatus
    && finalStatus.run_state === 'completed'
    && finalStatus.world_run_state === 'completed'
    && finalStatus.generated_video_time >= targetSeconds - 0.2
    && finalStatus.video_time >= targetSeconds - 0.2,
  );
  fs.writeFileSync(outputPath, `${JSON.stringify(result, null, 2)}\n`);
  log('demo complete', { outputPath, success: result.success, finalStatus });
  process.exit(result.success ? 0 : 2);
}

main().catch((error) => {
  const failure = {
    demo_name: demoName,
    workflow_id: workflowId,
    failed_at: nowIso(),
    error: error.stack || String(error),
  };
  try {
    fs.writeFileSync(outputPath, `${JSON.stringify(failure, null, 2)}\n`);
  } catch (_) {}
  console.error(error);
  process.exit(1);
});
