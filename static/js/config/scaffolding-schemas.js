// Author: Claude Sonnet 4.6
// Date: 2026-03-25 10:00
// PURPOSE: Scaffolding configuration schemas for ARC-AGI-3 web UI. Defines
//   SCAFFOLDING_SCHEMAS — the declarative field definitions (toggles, selects,
//   sliders, model selects) for each active scaffolding type (linear,
//   linear_interrupt, rgb). Drives dynamic settings panel rendering in state.js
//   renderScaffoldingSettings(). Also defines activeScaffoldingType global.
//   Extracted from state.js in Phase 3. Must load BEFORE state.js.
//   rlm, three_system, two_system, agent_spawn, world_model schemas removed
//   (harnesses hidden from UI; JS files kept for reference but not loaded).
// SRP/DRY check: Pass — schema definitions separated from rendering logic in state.js
// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING SCHEMAS CONFIG
// Extracted from state.js — Phase 3 modularization
// Load order: must be loaded before state.js
// ═══════════════════════════════════════════════════════════════════════════

// ═══════════════════════════════════════════════════════════════════════════
// SCAFFOLDING SCHEMAS
// ═══════════════════════════════════════════════════════════════════════════

let activeScaffoldingType = 'linear';

const _linearInputFields = [
  { type: 'select', id: 'inputGrid', label: 'Grid representation',
      options: [{v:'lp16',l:'LP16'},{v:'numeric',l:'Numeric'},{v:'rgb',l:'RGB-Agent'}], default: 'lp16' },
  { type: 'toggle', id: 'inputImage', label: 'Image', default: false, rowId: 'imageRow',
    labelHtml: 'Image <span class="opt-badge badge-img" id="imgBadge">IMG</span>' },
  { type: 'toggle', id: 'inputDiff', label: 'Diff (change map)', default: true },
  { type: 'toggle', id: 'inputHistogram', label: 'Color histogram', default: false },
  { type: 'toggle', id: 'reasoningTrace', label: 'Reasoning trace in history', default: false },
];
const _linearReasoningFields = [
  { type: 'model-select', id: 'modelSelect', capsId: 'modelCaps', testResultId: 'testResult' },
  { type: 'grid-2col', marginBottom: '8px', children: [
    { type: 'quadswitch', id: 'thinkingLevel', name: 'thinkingLevel', label: 'Thinking',
      options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
      hint: 'Thinking token budget' },
    { type: 'triswitch', id: 'toolsMode', name: 'toolsMode', label: 'Tool calls',
      options: [{v:'off',l:'Off'},{v:'on',l:'On',checked:true}],
      hint: 'On = Python sandbox' + (MODE === 'prod' ? ' (Pyodide)' : '') },
  ]},
  { type: 'multiswitch', id: 'planningMode', name: 'planMode', label: 'Planning horizon',
    options: [{v:'off',l:'Off'},{v:'5',l:'5'},{v:'10',l:'10',checked:true},{v:'15',l:'15'},{v:'20',l:'20'},{v:'unlimited',l:'\u221E'}],
    hint: 'LLM returns a multi-step plan instead of one action. Saves tokens.' },
  { type: 'number-spin', id: 'maxTokensLimit', label: 'Max tokens',
    default: 16384, min: 1024, max: 65536, step: 1024, spinFn: 'spinMaxTokens' },
];
const _linearCompactGroup = {
  subHeader: 'Compacting Model',
  toggleId: 'compactContext', toggleDefault: true, toggleOnChange: 'toggleCompactSettings()',
  bodyId: 'compactSettingsBody',
  fields: [
    { type: 'compact-model-select', id: 'compactModelSelectTop',
      hint: 'Used to summarize game history when context gets long.' },
    { type: 'grid-2col-body', children: [
      { type: 'number-input', id: 'compactAfter', label: 'After call #',
        placeholder: '\u2014', min: 1, max: 200, width: '55px' },
      { type: 'number-spin-unit', id: 'compactContextPct', unitId: 'contextLimitUnit',
        label: 'Context limit', default: 64000, min: 1, step: 1, width: '68px',
        spinFn: 'spinContextLimit', unitChangeFn: 'onContextLimitUnitChange()',
        units: [{v:'pct',l:'%'},{v:'tokens',l:'tok',selected:true}] },
      { type: 'toggle', id: 'compactOnLevel', label: 'Compact on new level', default: true },
    ]}
  ]
};
const _linearInterruptGroup = {
  subHeader: 'Interrupt Model',
  toggleId: 'interruptPlan', toggleDefault: true, toggleOnChange: 'toggleInterruptSettings()',
  bodyId: 'interruptSettingsBody',
  fields: [
    { type: 'compact-model-select', id: 'interruptModelSelect',
      hint: 'After each plan step, a cheap model checks if things went as expected. Interrupts if not.' },
  ]
};

const SCAFFOLDING_SCHEMAS = {
  linear: {
    id: 'linear',
    name: 'Linear',
    description: 'Reasoning model with optional compaction.',
    pipeline: [
      { id: 'compact', label: 'Compact', color: 'var(--purple)', settingsRef: 'compact', optional: true, enabledBy: 'compact.enabled' },
      { id: 'reasoning', label: 'Reasoning Model', color: 'var(--accent)', settingsRef: 'reasoning' },
    ],
    edges: [
      { from: 'compact', to: 'reasoning', label: 'resummarized' },
      { from: 'reasoning', to: 'compact', label: 'after N calls' },
    ],
    sections: [
      { id: 'secInput', label: 'Input', open: true, bodyClass: 'settings-grid', fields: _linearInputFields },
      {
        id: 'secReasoning', label: 'Reasoning', open: true,
        groups: [
          { subHeader: 'Reasoning Model', fields: _linearReasoningFields },
          _linearCompactGroup,
        ]
      },
      {
        id: 'secKeys', label: 'Model Keys', open: true,
        customHtml: function() {
          let h = '<div id="byokKeysContainer"></div>';
          if (FEATURES.copilot) {
            h += '<div id="copilotNotAuth">';
            h += '<div style="font-size:10px;color:var(--dim);margin-bottom:3px;text-transform:uppercase;letter-spacing:0.5px;">GitHub Copilot</div>';
            h += '<button class="btn btn-primary" onclick="copilotStartAuth()" style="width:100%;font-size:11px;">Connect GitHub Copilot</button>';
            h += '<div id="copilotDeviceCode" style="display:none;">';
            h += '<div class="copilot-code" id="copilotUserCode">\u2014\u2014\u2014\u2014</div>';
            h += '<div style="text-align:center;"><a id="copilotVerifyLink" href="#" target="_blank" class="copilot-link">Open GitHub to enter code</a></div>';
            h += '<div style="font-size:10px;color:var(--text-dim);margin-top:6px;text-align:center;">Waiting for authorization...</div>';
            h += '</div></div>';
            h += '<div id="copilotAuthed" style="display:none;">';
            h += '<div class="copilot-status"><span class="dot dot-green"></span><span style="color:var(--green);font-weight:600;">Connected</span></div>';
            h += '<div style="font-size:10px;color:var(--text-dim);margin-top:6px;">';
            h += 'Models: gpt-4.1, gpt-4o, gpt-5-mini<span class="tier-badge tier-free">FREE</span><br>';
            h += 'claude-sonnet-4, gemini-2.5-pro<span class="tier-badge tier-premium">PREMIUM</span></div></div>';
          }
          return h;
        }
      }
    ]
  },

  linear_interrupt: {
    id: 'linear_interrupt',
    name: 'Linear w/ Interrupt',
    description: 'Reasoning model with compaction and interrupt checking after each plan step.',
    pipeline: [
      { id: 'compact', label: 'Compact', color: 'var(--purple)', settingsRef: 'compact', optional: true, enabledBy: 'compact.enabled' },
      { id: 'reasoning', label: 'Reasoning Model', color: 'var(--accent)', settingsRef: 'reasoning' },
      { id: 'interrupt', label: 'Interrupt', color: 'var(--yellow)', settingsRef: 'interrupt', optional: true, enabledBy: 'interrupt.enabled' },
    ],
    edges: [
      { from: 'compact', to: 'reasoning', label: 'resummarized' },
      { from: 'reasoning', to: 'compact', label: 'after N calls' },
      { from: 'reasoning', to: 'interrupt', label: 'each plan step' },
      { from: 'interrupt', to: 'reasoning', label: 'if interrupted' },
    ],
    sections: [
      { id: 'secInput', label: 'Input', open: true, bodyClass: 'settings-grid', fields: _linearInputFields },
      {
        id: 'secReasoning', label: 'Reasoning', open: true,
        groups: [
          { subHeader: 'Reasoning Model', fields: _linearReasoningFields },
          _linearCompactGroup,
          _linearInterruptGroup,
        ]
      },
      {
        id: 'secKeys', label: 'Model Keys', open: true,
        customHtml: function() {
          let h = '<div id="byokKeysContainer"></div>';
          if (FEATURES.copilot) {
            h += '<div id="copilotNotAuth">';
            h += '<div style="font-size:10px;color:var(--dim);margin-bottom:3px;text-transform:uppercase;letter-spacing:0.5px;">GitHub Copilot</div>';
            h += '<button class="btn btn-primary" onclick="copilotStartAuth()" style="width:100%;font-size:11px;">Connect GitHub Copilot</button>';
            h += '<div id="copilotDeviceCode" style="display:none;">';
            h += '<div class="copilot-code" id="copilotUserCode">\u2014\u2014\u2014\u2014</div>';
            h += '<div style="text-align:center;"><a id="copilotVerifyLink" href="#" target="_blank" class="copilot-link">Open GitHub to enter code</a></div>';
            h += '<div style="font-size:10px;color:var(--text-dim);margin-top:6px;text-align:center;">Waiting for authorization...</div>';
            h += '</div></div>';
            h += '<div id="copilotAuthed" style="display:none;">';
            h += '<div class="copilot-status"><span class="dot dot-green"></span><span style="color:var(--green);font-weight:600;">Connected</span></div>';
            h += '<div style="font-size:10px;color:var(--text-dim);margin-top:6px;">';
            h += 'Models: gpt-4.1, gpt-4o, gpt-5-mini<span class="tier-badge tier-free">FREE</span><br>';
            h += 'claude-sonnet-4, gemini-2.5-pro<span class="tier-badge tier-premium">PREMIUM</span></div></div>';
          }
          return h;
        }
      }
    ]
  },

  rgb: {
    id: 'rgb',
    name: 'RGB (Read-Grep-Bash)',
    description: 'Analyzer reads game log with Read/Grep/Bash tools, outputs batched action plans. Based on alexisfox7/RGB-Agent.',
    pipeline: [
      { id: 'analyzer', label: 'Analyzer', color: 'var(--accent)', settingsRef: 'analyzer_model' },
      { id: 'read', label: 'Read', color: 'var(--green)', settingsRef: null },
      { id: 'grep', label: 'Grep', color: 'var(--cyan)', settingsRef: null },
      { id: 'bash', label: 'Bash', color: 'var(--yellow)', settingsRef: null },
      { id: 'queue', label: 'Action Queue', color: 'var(--purple)', settingsRef: null },
    ],
    edges: [
      { from: 'analyzer', to: 'read', label: 'tool call' },
      { from: 'analyzer', to: 'grep', label: 'tool call' },
      { from: 'analyzer', to: 'bash', label: 'tool call' },
      { from: 'read', to: 'analyzer', label: 'result' },
      { from: 'grep', to: 'analyzer', label: 'result' },
      { from: 'bash', to: 'analyzer', label: 'result' },
      { from: 'analyzer', to: 'queue', label: '[ACTIONS]' },
    ],
    sections: [
      {
        id: 'sf_rgb_secAnalyzer', label: 'Analyzer Model', open: true,
        groups: [{
          subHeader: 'Analyzer',
          fields: [
            { type: 'model-select', id: 'sf_rgb_analyzerModelSelect', capsId: 'sf_rgb_analyzerModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_rgb_analyzerThinking', name: 'sf_rgb_analyzerThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_rgb_analyzerMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
          ]
        }]
      },
      {
        id: 'sf_rgb_secParams', label: 'Parameters', open: true,
        groups: [{
          subHeader: 'Analysis',
          fields: [
            { type: 'number-input', id: 'sf_rgb_planSize', label: 'Plan size (actions per batch)', default: 5, min: 1, max: 20, width: '55px' },
            { type: 'number-input', id: 'sf_rgb_maxToolIter', label: 'Max tool iterations', default: 15, min: 1, max: 30, width: '55px' },
          ]
        }]
      },
      {
        id: 'secKeys', label: 'Model Keys', open: true,
        customHtml: function() { return '<div id="byokKeysContainer"></div>'; }
      }
    ]
  }
};
