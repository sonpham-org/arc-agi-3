// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Token estimation and pricing utilities for ARC-AGI-3 web UI. Provides
//   estimateTokens() (rough char/4 estimate) and cost calculation helpers.
//   Pricing comes from modelsData (live from /api/models) — no hardcoded prices.
//   Used by llm.js, scaffolding.js, and session.js for usage tracking and cost display.
//   Extracted from llm.js and scaffolding.js in Phase 3. Must load BEFORE those files.
// SRP/DRY check: Pass — token utilities only; pricing data comes from server
// ═══════════════════════════════════════════════════════════════════════════
// TOKENS UTILITY
// Load order: must be loaded before llm.js, scaffolding.js, session.js
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Rough token count estimate: 1 token ≈ 4 characters.
 */
function estimateTokens(text) {
  if (!text) return 0;
  return Math.ceil(text.length / 4);
}

/**
 * Look up [input, output, thinking?] pricing per 1M tokens for a model.
 * Uses live modelsData from /api/models (single source of truth in models.py).
 */
function _getModelPricing(modelKey) {
  const info = typeof getModelInfo === 'function' ? getModelInfo(modelKey) : null;
  if (info?.pricing && info.pricing.length >= 2) return info.pricing;
  return null;
}

/**
 * Format token usage as an HTML info line for display in the reasoning panel.
 */
function formatTokenInfo(resp, tokensObj) {
  // Use API-reported usage if available
  const tokens = tokensObj || sessionTotalTokens;
  let inputTok = resp.usage?.input_tokens || resp.usage?.prompt_tokens || 0;
  let outputTok = resp.usage?.output_tokens || resp.usage?.completion_tokens || 0;

  // Estimate input tokens from prompt length if not reported by API
  if (!inputTok && resp.prompt_length > 0) inputTok = Math.ceil(resp.prompt_length / 4);
  // Estimate output tokens from response text if not reported by API
  if (!outputTok) outputTok = estimateTokens(resp.raw || '');
  if (resp.thinking) outputTok += estimateTokens(resp.thinking);

  const totalTok = inputTok + outputTok;
  if (!totalTok) return '';

  // Cost estimate
  const model = resp.model || '';
  const prices = _getModelPricing(model);
  let costStr = '';
  if (prices) {
    const cost = (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
    tokens.input += inputTok;
    tokens.output += outputTok;
    tokens.cost += cost;
    costStr = ` · $${cost.toFixed(4)} (session: $${tokens.cost.toFixed(3)})`;
  } else {
    tokens.input += inputTok;
    tokens.output += outputTok;
  }

  return `<div style="font-size:10px;color:var(--text-dim);margin-bottom:2px;">` +
    `${inputTok.toLocaleString()} in + ${outputTok.toLocaleString()} out = ${totalTok.toLocaleString()} tok${costStr}</div>`;
}

/**
 * Track token usage for a single LLM call (used by agent_spawn scaffolding).
 * Replaces inner _asTrackUsage closure. Callers must pass tokensAccumulator explicitly.
 */
function trackTokenUsage(model, rawText, tokensAccumulator) {
  const usage = callLLM._lastUsage;
  let inputTok = usage?.input_tokens || 0;
  let outputTok = usage?.output_tokens || 0;
  if (!inputTok && rawText) inputTok = Math.ceil(rawText.length / 4);
  if (!outputTok && rawText) outputTok = Math.ceil(rawText.length / 4);
  tokensAccumulator.input += inputTok;
  tokensAccumulator.output += outputTok;
  const prices = _getModelPricing(model);
  let cost = 0;
  if (prices) {
    cost = (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
    tokensAccumulator.cost += cost;
  }
  callLLM._lastUsage = null;
  return { input_tokens: inputTok, output_tokens: outputTok, cost };
}
