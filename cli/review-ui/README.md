# GlassKit Eval Review UI

This Vite workspace builds the browser application embedded in the GlassKit Python package. The generated files are written to `../src/glasskit/eval/review/static/` and are committed so runtime users do not need Node.js.

Start the local Python review server first:

```bash
cd ..
uv run glasskit eval review --eval-dir tests/fixtures/eval_suites/review --port 8765 --no-open
```

Then start Vite in another shell. `/api` is proxied to the Python server:

```bash
npm ci
GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev
```

Use `npm run check` for lint, type checking, and unit tests. Use `npm run build` to type-check and replace the packaged static output. The browser preview is intentionally best effort; eval decoding still uses PyAV and may select an adjacent frame.
