# GlassKit Eval Review UI

This Vite workspace builds the browser application embedded in the GlassKit Python package. Generated files are written to `../src/glasskit/eval/review/static/`, ignored by Git, and produced automatically by the Python package build hook. Published wheels and source distributions still contain the complete UI, so runtime users do not need Node.js.

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

Use `npm run check` for lint, type checking, and unit tests. Use `npm run build` when you want to exercise the packaged static output directly; `uv build` also runs this build automatically. The browser preview is intentionally best effort; eval decoding still uses PyAV and may select an adjacent frame.
