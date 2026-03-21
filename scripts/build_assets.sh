#!/bin/bash
# Build script: concatenate JS in load order, minify JS + CSS with esbuild
set -e
cd "$(dirname "$0")/.."

STATIC="static"
JS_OUT="$STATIC/js/bundle.min.js"
CSS_OUT="$STATIC/css/main.min.css"

# JS files in exact load order from index.html
JS_FILES=(
  "$STATIC/js/utils/formatting.js"
  "$STATIC/js/config/scaffolding-schemas.js"
  "$STATIC/js/state.js"
  "$STATIC/js/engine.js"
  "$STATIC/js/reasoning.js"
  "$STATIC/js/utils/tokens.js"
  "$STATIC/js/rendering/grid-renderer.js"
  "$STATIC/js/ui-models.js"
  "$STATIC/js/ui-tokens.js"
  "$STATIC/js/ui-tabs.js"
  "$STATIC/js/ui-grid.js"
  "$STATIC/js/ui.js"
  "$STATIC/js/utils/json-parsing.js"
  "$STATIC/js/llm-config.js"
  "$STATIC/js/llm-timeline.js"
  "$STATIC/js/llm-reasoning.js"
  "$STATIC/js/llm-controls.js"
  "$STATIC/js/llm-executor.js"
  "$STATIC/js/llm.js"
  "$STATIC/js/scaffolding.js"
  "$STATIC/js/scaffolding-rlm.js"
  "$STATIC/js/scaffolding-three-system.js"
  "$STATIC/js/scaffolding-agent-spawn.js"
  "$STATIC/js/scaffolding-world-model.js"
  "$STATIC/js/scaffolding-linear.js"
  "$STATIC/js/scaffolding-rgb.js"
  "$STATIC/js/session-storage.js"
  "$STATIC/js/session-replay.js"
  "$STATIC/js/session-persistence.js"
  "$STATIC/js/session-views-grid.js"
  "$STATIC/js/session-views-history.js"
  "$STATIC/js/session-views.js"
  "$STATIC/js/auth.js"
  "$STATIC/js/session.js"
  "$STATIC/js/observatory/obs-log-renderer.js"
  "$STATIC/js/observatory/obs-scrubber.js"
  "$STATIC/js/observatory/obs-swimlane-renderer.js"
  "$STATIC/js/observatory/obs-memory.js"
  "$STATIC/js/memory-inspector.js"
  "$STATIC/js/observatory/obs-lifecycle.js"
  "$STATIC/js/observatory.js"
  "$STATIC/js/human-social.js"
  "$STATIC/js/human-render.js"
  "$STATIC/js/human-input.js"
  "$STATIC/js/human-session.js"
  "$STATIC/js/human-game.js"
  "$STATIC/js/human.js"
  "$STATIC/js/leaderboard.js"
  "$STATIC/js/dev.js"
)

echo "=== Building JS bundle ==="
BUNDLE_TMP=$(mktemp --suffix=.js)
for f in "${JS_FILES[@]}"; do
  cat "$f" >> "$BUNDLE_TMP"
  echo ";" >> "$BUNDLE_TMP"
done

RAW_SIZE=$(wc -c < "$BUNDLE_TMP")
npx esbuild --minify --target=es2020 "$BUNDLE_TMP" --outfile="$JS_OUT"
MIN_SIZE=$(wc -c < "$JS_OUT")
echo "  Raw: $((RAW_SIZE / 1024)) KB → Minified: $((MIN_SIZE / 1024)) KB ($((100 - MIN_SIZE * 100 / RAW_SIZE))% smaller)"
rm "$BUNDLE_TMP"

echo "=== Building CSS ==="
CSS_RAW=$(wc -c < "$STATIC/css/main.css")
npx esbuild --minify "$STATIC/css/main.css" --outfile="$CSS_OUT"
CSS_MIN=$(wc -c < "$CSS_OUT")
echo "  Raw: $((CSS_RAW / 1024)) KB → Minified: $((CSS_MIN / 1024)) KB ($((100 - CSS_MIN * 100 / CSS_RAW))% smaller)"

echo "=== Done ==="
echo "  $JS_OUT ($((MIN_SIZE / 1024)) KB)"
echo "  $CSS_OUT ($((CSS_MIN / 1024)) KB)"
