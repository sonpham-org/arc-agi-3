# E2E Tests — Playwright

## Setup

```bash
pip install pytest-playwright
playwright install chromium
```

## Prerequisites

- **Server running**: `python server.py --mode staging --port 5050`
- **LM Studio running**: `localhost:1234` with at least one model loaded

## Run

```bash
# All E2E tests (headless)
pytest tests/e2e/ -v

# With visible browser
pytest tests/e2e/ -v --headed

# Single test class
pytest tests/e2e/test_lmstudio_regression.py::TestModelDiscovery -v --headed

# Single test
pytest tests/e2e/test_lmstudio_regression.py::TestLMStudioLinear::test_autoplay_fires_lmstudio_proxy -v --headed

# Custom server URL
ARC_TEST_URL=http://localhost:3000 pytest tests/e2e/ -v
```

## Test Coverage

| Class | What it tests |
|---|---|
| `TestModelDiscovery` | LM Studio models appear in modelsData, dummy key set, models in dropdown |
| `TestSessionSetup` | Navigate to #agent, create session, select game |
| `TestLMStudioLinear` | Select LM Studio model, autoplay fires proxy, gets response |
| `TestLMStudioThreeSystem` | Three-system scaffolding routes through proxy |
| `TestLMStudioErrors` | No empty `{}` error objects in console |
| `TestProxyRequestFormat` | Proxy request has model/messages/base_url, system→user promotion |
