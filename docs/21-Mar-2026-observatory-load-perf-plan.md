# Observatory Load Performance Plan

**Date:** 2026-03-21
**Goal:** Reduce page load time by bundling, minifying, and compressing static assets.

---

## Problem

- 49 blocking `<script>` tags = 49 sequential HTTP requests
- 884 KB unminified JS, 71 KB CSS, 49 KB HTML = ~1 MB total
- No gzip/brotli compression from Gunicorn
- Each script blocks HTML parsing — page is blank until all 49 download + execute

## Scope

### In Scope
- Bundle all JS into a single file (`bundle.min.js`)
- Minify JS with esbuild (fast, zero-config)
- Minify CSS
- Add Flask-Compress for gzip/brotli on the wire
- Update index.html to load the single bundle with `defer`
- Build script that runs pre-deploy (no npm/webpack dependency at runtime)

### Out of Scope
- Code splitting / lazy loading (overkill for SPA)
- ES modules migration (would require rewriting all globals)
- CDN / edge caching (Railway handles this)
- Image optimization (no images to speak of)

## Architecture

### Build script: `scripts/build_assets.sh`

```bash
#!/bin/bash
# Concatenate all JS files in load order → bundle.js
# Minify with esbuild → bundle.min.js
# Minify CSS → main.min.css
```

Key points:
- **Load order preserved** — concatenation follows the exact `<script>` order in index.html
- **No runtime dependency** — esbuild is a single binary, runs in <100ms
- **Source files untouched** — dev can still load individual files by switching template
- **Idempotent** — safe to run multiple times

### Template changes

`index.html` switches from 49 `<script>` tags to:
```html
<script defer src="/static/js/bundle.min.js?v={{ static_v }}"></script>
```

CSS switches from:
```html
<link rel="stylesheet" href="/static/css/main.css?v={{ static_v }}">
```
to:
```html
<link rel="stylesheet" href="/static/css/main.min.css?v={{ static_v }}">
```

### Flask-Compress

Add to `requirements.txt` and `server/app.py`:
```python
from flask_compress import Compress
Compress(app)
```

This automatically gzip/brotli compresses responses >500 bytes.

## Expected Results

| Metric | Before | After |
|--------|--------|-------|
| HTTP requests (JS) | 49 | 1 |
| JS payload (raw) | 884 KB | ~350 KB (minified) |
| JS over wire (compressed) | 884 KB | ~90 KB |
| CSS over wire | 71 KB | ~12 KB |
| HTML parsing blocked | Yes (all 49) | No (defer) |

## TODOs

1. [x] Install esbuild
2. [x] Create `scripts/build_assets.sh` — concatenate + minify
3. [x] Run build, generate `bundle.min.js` and `main.min.css`
4. [x] Update `index.html` — replace 49 script tags with 1 deferred bundle
5. [x] Add Flask-Compress to requirements.txt and server/app.py
6. [x] Also update share.html, obs.html if they load the same scripts
7. [x] Test locally
8. [ ] Push to staging, verify

## Docs / Changelog

- CHANGELOG.md entry for bundle + compress
