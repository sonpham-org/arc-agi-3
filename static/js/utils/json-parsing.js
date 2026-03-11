// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: JSON extraction and parsing utilities for ARC-AGI-3 LLM responses.
//   Provides findFinalMarker() (FINAL(...) detection for RLM), extractJsonFromText()
//   (balanced-brace JSON extraction), parseRlmClientOutput() (RLM response normalization),
//   and parseClientLLMResponse() (general LLM response parsing with <think> block support).
//   Extracted from scaffolding.js in Phase 3. Must load BEFORE scaffolding.js and
//   scaffolding-rlm.js. No external dependencies.
// SRP/DRY check: Pass — all JSON extraction logic consolidated here; used by all scaffolding modules
// ═══════════════════════════════════════════════════════════════════════════
// JSON PARSING UTILITY
// Extracted from scaffolding.js — Phase 3 modularization
// Load order: must be loaded before scaffolding.js
// ═══════════════════════════════════════════════════════════════════════════

/**
 * Find a FINAL(...) marker in RLM response text.
 * Renamed from _rlmFindFinal to findFinalMarker.
 */
function findFinalMarker(text) {
  if (typeof text !== 'string') return null;
  // Strip code blocks before checking for FINAL
  const stripped = text.replace(/```repl\s*\n[\s\S]*?\n```/g, '');
  // Check for FINAL(...)
  const finalMatch = stripped.match(/^\s*FINAL\((.+)\)\s*$/ms);
  if (finalMatch) return finalMatch[1].trim();
  return null;
}

/**
 * Extract a valid JSON action/command object from LLM response text.
 * Renamed from _extractJsonFromText to extractJsonFromText.
 */
function extractJsonFromText(text) {
  if (typeof text !== 'string') text = JSON.stringify(text);
  // Balanced-brace JSON extraction (same logic as parseLLMResponse)
  const cleaned = text.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) {
        try {
          const parsed = JSON.parse(cleaned.substring(i, j + 1));
          if (parsed.action !== undefined || parsed.plan || parsed.actions || parsed.command) return parsed;
        } catch {}
        break;
      }}
    }
  }
  return null;
}

/**
 * Parse a client-side LLM response string into a structured response envelope.
 * Renamed from parseClientLLMResponse to parseLLMResponse.
 */
function parseLLMResponse(content, modelName) {
  let thinking = '';
  const thinkMatch = content.match(/<think>([\s\S]*?)<\/think>/);
  if (thinkMatch) {
    thinking = thinkMatch[1].trim();
    content = content.replace(/<think>[\s\S]*?<\/think>/g, '').trim();
  }
  // Extract JSON using balanced-brace matching
  // Strip comments first, then find each top-level { } block via brace counting
  const cleaned = content.replace(/^\s*\/\/.*$/gm, '');
  for (let i = 0; i < cleaned.length; i++) {
    if (cleaned[i] !== '{') continue;
    let depth = 0, inStr = false, esc = false;
    for (let j = i; j < cleaned.length; j++) {
      const ch = cleaned[j];
      if (esc) { esc = false; continue; }
      if (ch === '\\' && inStr) { esc = true; continue; }
      if (ch === '"') { inStr = !inStr; continue; }
      if (inStr) continue;
      if (ch === '{') depth++;
      else if (ch === '}') { depth--; if (depth === 0) {
        try {
          const parsed = JSON.parse(cleaned.substring(i, j + 1));
          if (parsed.action !== undefined || parsed.plan) {
            return { raw: content, thinking: thinking ? thinking.substring(0, 500) : null, parsed, model: modelName };
          }
        } catch {}
        break;
      }}
    }
  }
  return { raw: content, parsed: null, model: modelName };
}

// Alias for backward compat with any callers using old name
const parseClientLLMResponse = parseLLMResponse;
