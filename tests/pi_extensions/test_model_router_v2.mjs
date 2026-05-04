import test from 'node:test';
import assert from 'node:assert/strict';

import {
  classifyPrompt,
  shouldAutoSwitch,
  chooseFirstAvailableTarget,
  buildEffectiveConfig,
  DEFAULT_CONFIG,
} from '../../.pi/extensions/model-router-v2/core.ts';

test('classifyPrompt prefers frontend design for strong UI/UX prompt', () => {
  const result = classifyPrompt('Design a polished landing page hero with better UX, layout, and visual hierarchy.', DEFAULT_CONFIG);

  assert.equal(result.route, 'frontend_design');
  assert.equal(result.confidence, 'high');
  assert.ok(result.scores.frontend_design > result.scores.hard_reasoning);
});

test('classifyPrompt avoids ambiguous routing when signals are too close', () => {
  const result = classifyPrompt('Investigate frontend architecture and UI layout tradeoffs.', DEFAULT_CONFIG);

  assert.equal(result.ambiguous, true);
  assert.equal(result.route, undefined);
});

test('shouldAutoSwitch is conservative when current model is already acceptable fallback', () => {
  const decision = shouldAutoSwitch({
    route: DEFAULT_CONFIG.routes.frontend_design,
    classification: {
      route: 'frontend_design',
      confidence: 'high',
      ambiguous: false,
      scores: { hard_reasoning: 0, fast_code: 0, smart_small_refactor: 0, frontend_design: 7 },
      matched: { frontend_design: ['landing page', 'ux'] },
      reason: 'frontend_design won score 7',
    },
    currentModel: { provider: 'anthropic', id: 'claude-sonnet-4-6' },
  });

  assert.equal(decision.shouldSwitch, false);
  assert.match(decision.reason, /acceptable/i);
});

test('chooseFirstAvailableTarget falls back when primary is unavailable', () => {
  const chosen = chooseFirstAvailableTarget(
    DEFAULT_CONFIG.routes.frontend_design,
    [
      { provider: 'anthropic', id: 'claude-sonnet-4-6' },
      { provider: 'openai-codex', id: 'gpt-5.4' },
    ],
  );

  assert.equal(chosen.target.provider, 'anthropic');
  assert.equal(chosen.target.modelId, 'claude-sonnet-4-6');
  assert.equal(chosen.usedFallback, true);
});

test('buildEffectiveConfig applies overrides without mutating defaults', () => {
  const config = buildEffectiveConfig({
    thresholds: { highConfidenceScore: 9 },
    routes: {
      fast_code: {
        target: {
          provider: 'anthropic',
          modelId: 'claude-haiku-4-5',
          thinkingLevel: 'minimal',
          reason: 'fast override',
        },
      },
    },
  });

  assert.equal(config.thresholds.highConfidenceScore, 9);
  assert.equal(config.routes.fast_code.target.provider, 'anthropic');
  assert.equal(DEFAULT_CONFIG.routes.fast_code.target.provider, 'openai-codex');
});
