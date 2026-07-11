# GlassKit Eval Review UI

This Vite workspace builds the browser application embedded in the GlassKit Python package. Generated files are written to `../src/glasskit/eval/review/static/`, ignored by Git, and produced automatically by the Python package build hook. Published wheels and source distributions still contain the complete UI, so runtime users do not need Node.js.

Editable installs intentionally skip the frontend build, so a clean source checkout does not initially contain the ignored static bundle required by the Python server. Install the frontend dependencies and generate that bundle once:

```bash
npm install
npm run build
```

Then start the local Python review server:

```bash
cd ..
uv run glasskit eval review --eval-dir tests/fixtures/eval_directories/review --port 8765 --no-open
```

Start Vite in another shell. `/api` is proxied to the Python server:

```bash
GLASSKIT_REVIEW_BACKEND=http://127.0.0.1:8765 npm run dev
```

Use `npm run fix` to apply lint fixes and formatting, and use `npm run check` for read-only lint and format checks, type checking, and unit tests. Use `npm run build` when you want to exercise the packaged static output directly; `uv build` first restores the locked dependencies with `npm ci` and then runs this build automatically. The browser preview is intentionally best effort; eval decoding still uses PyAV and may select an adjacent frame.
