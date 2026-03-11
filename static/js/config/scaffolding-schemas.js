// Author: Mark Barney + Cascade (Claude Opus 4.6 thinking)
// Date: 2026-03-11 13:47
// PURPOSE: Scaffolding configuration schemas for ARC-AGI-3 web UI. Defines
//   SCAFFOLDING_SCHEMAS — the declarative field definitions (toggles, selects,
//   sliders, model selects) for each scaffolding type (linear, rlm, three_system,
//   two_system, agent_spawn). Drives dynamic settings panel rendering in state.js
//   renderScaffoldingSettings(). Also defines activeScaffoldingType global.
//   Extracted from state.js in Phase 3. Must load BEFORE state.js.
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
  { type: 'toggle', id: 'inputGrid', label: 'Full grid (RLE)', default: true },
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

  rlm: {
    id: 'rlm',
    name: 'RLM (Recursive)',
    description: 'Root LM spawns sub-calls via REPL with persistent memory.',
    pipeline: [
      { id: 'root_lm', label: 'Root LM', color: 'var(--accent)', settingsRef: 'root_model' },
      { id: 'repl', label: 'REPL Environment', color: 'var(--green)', settingsRef: null },
      { id: 'sub_lm', label: 'Recursive LM', color: 'var(--purple)', settingsRef: 'sub_model' },
      { id: 'memory', label: 'Memory Store', color: 'var(--yellow)', settingsRef: null },
    ],
    edges: [
      { from: 'root_lm', to: 'repl', label: 'code output' },
      { from: 'repl', to: 'sub_lm', label: 'sub-call' },
      { from: 'sub_lm', to: 'repl', label: 'result' },
      { from: 'repl', to: 'memory', label: 'store/retrieve' },
      { from: 'repl', to: 'root_lm', label: 'final answer' },
    ],
    sections: [
      {
        id: 'sf_rlm_secInput', label: 'Input', open: true, bodyClass: 'settings-grid',
        fields: [
          { type: 'toggle', id: 'sf_rlm_inputGrid', label: 'Full grid (RLE)', default: true },
          { type: 'toggle', id: 'sf_rlm_inputImage', label: 'Image', default: false },
          { type: 'toggle', id: 'sf_rlm_inputDiff', label: 'Diff (change map)', default: true },
          { type: 'toggle', id: 'sf_rlm_inputHistogram', label: 'Color histogram', default: false },
        ]
      },
      {
        id: 'sf_rlm_secRoot', label: 'Root Model', open: true,
        groups: [{
          subHeader: 'Root LM',
          fields: [
            { type: 'model-select', id: 'sf_rlm_modelSelect', capsId: 'sf_rlm_modelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_rlm_thinking', name: 'sf_rlm_thinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_rlm_maxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
            { type: 'multiswitch', id: 'sf_rlm_planningMode', name: 'sf_rlm_planMode', label: 'Planning horizon',
              options: [{v:'off',l:'Off'},{v:'5',l:'5'},{v:'10',l:'10',checked:true},{v:'15',l:'15'},{v:'20',l:'20'},{v:'unlimited',l:'\u221E'}],
              hint: 'LLM returns a multi-step plan instead of one action. Saves tokens.' },
          ]
        }]
      },
      {
        id: 'sf_rlm_secSub', label: 'Sub Model', open: true,
        groups: [{
          subHeader: 'Recursive LM',
          fields: [
            { type: 'model-select', id: 'sf_rlm_subModelSelect', capsId: 'sf_rlm_subModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_rlm_subThinking', name: 'sf_rlm_subThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_rlm_subMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
          ]
        }]
      },
      {
        id: 'sf_rlm_secRecursion', label: 'Recursion', open: true,
        groups: [{
          subHeader: 'Recursion Limits',
          fields: [
            { type: 'number-input', id: 'sf_rlm_maxDepth', label: 'Max depth', default: 3, min: 1, max: 10, width: '55px' },
            { type: 'number-input', id: 'sf_rlm_maxIter', label: 'Max iterations', default: 10, min: 1, max: 100, width: '55px' },
            { type: 'number-input', id: 'sf_rlm_outputTrunc', label: 'Output truncation (chars)', default: 5000, min: 100, max: 50000, width: '75px' },
          ]
        }]
      },
      {
        id: 'secKeys', label: 'Model Keys', open: true,
        customHtml: function() { return '<div id="byokKeysContainer"></div>'; }
      }
    ]
  },

  three_system: {
    id: 'three_system',
    name: '3-System (PWM)',
    description: 'Planner reasons via simulation, Monitor checks each step, World Model learns rules.',
    pipeline: [
      { id: 'planner', label: 'Planner', color: 'var(--accent)', settingsRef: 'planner_model' },
      { id: 'executor', label: 'Executor', color: 'var(--green)', settingsRef: null },
      { id: 'monitor', label: 'Monitor', color: 'var(--yellow)', settingsRef: 'monitor_model' },
      { id: 'world_model', label: 'World Model', color: 'var(--purple)', settingsRef: 'wm_model' },
    ],
    edges: [
      { from: 'planner', to: 'world_model', label: 'simulate' },
      { from: 'planner', to: 'executor', label: 'commit plan' },
      { from: 'executor', to: 'monitor', label: 'check step' },
      { from: 'monitor', to: 'planner', label: 'replan' },
      { from: 'executor', to: 'world_model', label: 'observations' },
    ],
    sections: [
      {
        id: 'sf_ts_secInput', label: 'Input', open: true, bodyClass: 'settings-grid',
        fields: [
          { type: 'toggle', id: 'sf_ts_inputGrid', label: 'Full grid (RLE)', default: true },
          { type: 'toggle', id: 'sf_ts_inputImage', label: 'Image', default: false },
          { type: 'toggle', id: 'sf_ts_inputDiff', label: 'Diff (change map)', default: true },
          { type: 'toggle', id: 'sf_ts_inputHistogram', label: 'Color histogram', default: false },
        ]
      },
      {
        id: 'sf_ts_secPlanner', label: 'Planner', open: true,
        groups: [{
          subHeader: 'Planner Model',
          fields: [
            { type: 'model-select', id: 'sf_ts_plannerModelSelect', capsId: 'sf_ts_plannerModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_ts_plannerThinking', name: 'sf_ts_plannerThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_ts_plannerMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
            { type: 'multiswitch', id: 'sf_ts_planHorizon', name: 'sf_ts_planHorizon', label: 'Planning horizon',
              options: [{v:'3',l:'3'},{v:'5',l:'5',checked:true},{v:'8',l:'8'},{v:'10',l:'10'},{v:'15',l:'15'},{v:'20',l:'20'}],
              hint: 'Min actions per plan. Monitor can interrupt early.' },
          ]
        }]
      },
      {
        id: 'sf_ts_secMonitor', label: 'Monitor', open: true,
        groups: [{
          subHeader: 'Monitor Model',
          fields: [
            { type: 'model-select', id: 'sf_ts_monitorModelSelect', capsId: 'sf_ts_monitorModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_ts_monitorThinking', name: 'sf_ts_monitorThinking', label: 'Thinking',
                options: [{v:'off',l:'Off',checked:true},{v:'low',l:'Low'},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_ts_monitorMaxTokens', label: 'Max tokens',
                default: 4096, min: 1024, max: 16384, step: 1024, spinFn: null, inline: true },
            ]},
            { type: 'multiswitch', id: 'sf_ts_replanCooldown', name: 'sf_ts_replanCooldown', label: 'Replan cooldown',
              options: [{v:'1',l:'1'},{v:'2',l:'2'},{v:'3',l:'3',checked:true},{v:'5',l:'5'},{v:'10',l:'10'}],
              hint: 'Min plans between replans. Higher = more conservative.' },
          ]
        }]
      },
      {
        id: 'sf_ts_secWorldModel', label: 'World Model', open: true,
        groups: [{
          subHeader: 'World Model',
          fields: [
            { type: 'model-select', id: 'sf_ts_wmModelSelect', capsId: 'sf_ts_wmModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_ts_wmThinking', name: 'sf_ts_wmThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_ts_wmMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
          ]
        }]
      },
      {
        id: 'sf_ts_secParams', label: 'Parameters', open: true,
        groups: [{
          subHeader: 'Tuning',
          fields: [
            { type: 'number-input', id: 'sf_ts_plannerMaxTurns', label: 'Planner max turns', default: 10, min: 1, max: 15, width: '55px' },
            { type: 'number-input', id: 'sf_ts_wmMaxTurns', label: 'WM max turns', default: 5, min: 1, max: 10, width: '55px' },
            { type: 'number-input', id: 'sf_ts_wmUpdateEvery', label: 'WM update every N steps', default: 5, min: 1, max: 20, width: '55px' },
            { type: 'number-input', id: 'sf_ts_maxPlanLength', label: 'Max plan length', default: 15, min: 3, max: 30, width: '55px' },
          ]
        }]
      },
      {
        id: 'secKeys', label: 'Model Keys', open: true,
        customHtml: function() { return '<div id="byokKeysContainer"></div>'; }
      }
    ]
  },

  two_system: {
    id: 'two_system',
    name: '2-System (PM)',
    description: 'Planner reasons via analysis, Monitor checks each step. No World Model.',
    pipeline: [
      { id: 'planner', label: 'Planner', color: 'var(--accent)', settingsRef: 'planner_model' },
      { id: 'executor', label: 'Executor', color: 'var(--green)', settingsRef: null },
      { id: 'monitor', label: 'Monitor', color: 'var(--yellow)', settingsRef: 'monitor_model' },
    ],
    edges: [
      { from: 'planner', to: 'executor', label: 'commit plan' },
      { from: 'executor', to: 'monitor', label: 'check step' },
      { from: 'monitor', to: 'planner', label: 'replan' },
    ],
    sections: [
      {
        id: 'sf_2s_secInput', label: 'Input', open: true, bodyClass: 'settings-grid',
        fields: [
          { type: 'toggle', id: 'sf_2s_inputGrid', label: 'Full grid (RLE)', default: true },
          { type: 'toggle', id: 'sf_2s_inputImage', label: 'Image', default: false },
          { type: 'toggle', id: 'sf_2s_inputDiff', label: 'Diff (change map)', default: true },
          { type: 'toggle', id: 'sf_2s_inputHistogram', label: 'Color histogram', default: false },
        ]
      },
      {
        id: 'sf_2s_secPlanner', label: 'Planner', open: true,
        groups: [{
          subHeader: 'Planner Model',
          fields: [
            { type: 'model-select', id: 'sf_2s_plannerModelSelect', capsId: 'sf_2s_plannerModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_2s_plannerThinking', name: 'sf_2s_plannerThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_2s_plannerMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
            { type: 'multiswitch', id: 'sf_2s_planHorizon', name: 'sf_2s_planHorizon', label: 'Planning horizon',
              options: [{v:'3',l:'3'},{v:'5',l:'5',checked:true},{v:'8',l:'8'},{v:'10',l:'10'},{v:'15',l:'15'},{v:'20',l:'20'}],
              hint: 'Min actions per plan. Monitor can interrupt early.' },
          ]
        }]
      },
      {
        id: 'sf_2s_secMonitor', label: 'Monitor', open: true,
        groups: [{
          subHeader: 'Monitor Model',
          fields: [
            { type: 'model-select', id: 'sf_2s_monitorModelSelect', capsId: 'sf_2s_monitorModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_2s_monitorThinking', name: 'sf_2s_monitorThinking', label: 'Thinking',
                options: [{v:'off',l:'Off',checked:true},{v:'low',l:'Low'},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_2s_monitorMaxTokens', label: 'Max tokens',
                default: 4096, min: 1024, max: 16384, step: 1024, spinFn: null, inline: true },
            ]},
            { type: 'multiswitch', id: 'sf_2s_replanCooldown', name: 'sf_2s_replanCooldown', label: 'Replan cooldown',
              options: [{v:'1',l:'1'},{v:'2',l:'2'},{v:'3',l:'3',checked:true},{v:'5',l:'5'},{v:'10',l:'10'}],
              hint: 'Min plans between replans. Higher = more conservative.' },
          ]
        }]
      },
      {
        id: 'sf_2s_secParams', label: 'Parameters', open: true,
        groups: [{
          subHeader: 'Tuning',
          fields: [
            { type: 'number-input', id: 'sf_2s_plannerMaxTurns', label: 'Planner max turns', default: 10, min: 1, max: 15, width: '55px' },
            { type: 'number-input', id: 'sf_2s_maxPlanLength', label: 'Max plan length', default: 15, min: 3, max: 30, width: '55px' },
          ]
        }]
      },
      {
        id: 'secKeys', label: 'Model Keys', open: true,
        customHtml: function() { return '<div id="byokKeysContainer"></div>'; }
      }
    ]
  },
  agent_spawn: {
    id: 'agent_spawn',
    name: 'Agent Spawn',
    description: 'Agentica-style orchestrator delegates to explorer/theorist/tester/solver subagents.',
    pipeline: [
      { id: 'orchestrator', label: 'Orchestrator', color: 'var(--accent)', settingsRef: 'orchestrator_model' },
      { id: 'explorer', label: 'Explorer', color: 'var(--green)', settingsRef: null },
      { id: 'theorist', label: 'Theorist', color: 'var(--cyan)', settingsRef: null },
      { id: 'tester', label: 'Tester', color: 'var(--yellow)', settingsRef: null },
      { id: 'solver', label: 'Solver', color: 'var(--purple)', settingsRef: null },
      { id: 'memory', label: 'Memory', color: 'var(--orange)', settingsRef: null },
    ],
    edges: [
      { from: 'orchestrator', to: 'explorer', label: 'delegate' },
      { from: 'orchestrator', to: 'theorist', label: 'delegate' },
      { from: 'orchestrator', to: 'tester', label: 'delegate' },
      { from: 'orchestrator', to: 'solver', label: 'delegate' },
      { from: 'explorer', to: 'memory', label: 'report' },
      { from: 'theorist', to: 'memory', label: 'report' },
      { from: 'tester', to: 'memory', label: 'report' },
      { from: 'solver', to: 'memory', label: 'report' },
      { from: 'memory', to: 'orchestrator', label: 'context' },
    ],
    sections: [
      {
        id: 'sf_as_secInput', label: 'Input', open: true, bodyClass: 'settings-grid',
        fields: [
          { type: 'toggle', id: 'sf_as_inputGrid', label: 'Full grid (RLE)', default: true },
          { type: 'toggle', id: 'sf_as_inputImage', label: 'Image', default: false },
          { type: 'toggle', id: 'sf_as_inputDiff', label: 'Diff (change map)', default: true },
          { type: 'toggle', id: 'sf_as_inputHistogram', label: 'Color histogram', default: false },
        ]
      },
      {
        id: 'sf_as_secOrchestrator', label: 'Orchestrator', open: true,
        groups: [{
          subHeader: 'Orchestrator Model',
          fields: [
            { type: 'model-select', id: 'sf_as_orchestratorModelSelect', capsId: 'sf_as_orchestratorModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_as_orchestratorThinking', name: 'sf_as_orchestratorThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_as_orchestratorMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
          ]
        }]
      },
      {
        id: 'sf_as_secSubagent', label: 'Subagent', open: true,
        groups: [{
          subHeader: 'Subagent Model',
          fields: [
            { type: 'model-select', id: 'sf_as_subagentModelSelect', capsId: 'sf_as_subagentModelCaps' },
            { type: 'grid-2col', marginBottom: '8px', children: [
              { type: 'quadswitch', id: 'sf_as_subagentThinking', name: 'sf_as_subagentThinking', label: 'Thinking',
                options: [{v:'off',l:'Off'},{v:'low',l:'Low',checked:true},{v:'med',l:'Med'},{v:'high',l:'High'}],
                hint: 'Thinking token budget' },
              { type: 'number-spin', id: 'sf_as_subagentMaxTokens', label: 'Max tokens',
                default: 16384, min: 1024, max: 65536, step: 1024, spinFn: null, inline: true },
            ]},
          ]
        }]
      },
      {
        id: 'sf_as_secParams', label: 'Parameters', open: true,
        groups: [{
          subHeader: 'Tuning',
          fields: [
            { type: 'number-input', id: 'sf_as_maxSubagentBudget', label: 'Max subagent budget', default: 5, min: 1, max: 10, width: '55px' },
            { type: 'number-input', id: 'sf_as_orchestratorMaxTurns', label: 'Orchestrator max turns', default: 5, min: 1, max: 15, width: '55px' },
            { type: 'number-input', id: 'sf_as_orchestratorHistoryLength', label: 'History length', default: 10, min: 1, max: 50, width: '55px' },
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
