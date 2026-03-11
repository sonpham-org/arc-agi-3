// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Token estimation and pricing utilities for ARC-AGI-3 web UI. Provides
//   estimateTokens() (rough char/4 estimate), TOKEN_PRICES lookup table for all
//   supported models (input/output $/M tokens), and cost calculation helpers.
//   Used by llm.js, scaffolding.js, and session.js for usage tracking and cost display.
//   Extracted from llm.js and scaffolding.js in Phase 3. Must load BEFORE those files.
// SRP/DRY check: Pass — single source of truth for token estimation and pricing
// ═══════════════════════════════════════════════════════════════════════════
// TOKENS UTILITY
// Extracted from llm.js and scaffolding.js — Phase 3 modularization
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
 * Per-1M-token pricing table [input $/1M, output $/1M].
 */
const TOKEN_PRICES = {
  // [input $/1M tok, output $/1M tok]
  'gemini-3.1-pro': [2.0, 12.0],
  'gemini-3-pro': [2.0, 12.0],
  'gemini-3-flash': [0.50, 3.0],
  'gemini-2.5-pro': [1.25, 10.0],
  'gemini-2.5-flash': [0.30, 2.50],
  'gemini-2.5-flash-lite': [0.10, 0.40],
  'gemini-2.0-flash': [0.10, 0.40],
  'gemini-2.0-flash-lite': [0.075, 0.30],
  'claude-sonnet-4-6': [3.0, 15.0],
  'claude-sonnet-4-5': [3.0, 15.0],
  'claude-haiku-4-5': [0.80, 4.0],
  'gpt-4o': [2.50, 10.0],
  'gpt-4o-mini': [0.15, 0.60],
};

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
  const prices = TOKEN_PRICES[model] || null;
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
  const prices = TOKEN_PRICES[model] || null;
  let cost = 0;
  if (prices) {
    cost = (inputTok * prices[0] + outputTok * prices[1]) / 1_000_000;
    tokensAccumulator.cost += cost;
  }
  callLLM._lastUsage = null;
  return { input_tokens: inputTok, output_tokens: outputTok, cost };
}
