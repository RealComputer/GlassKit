This package provides the `@glasskit.ai/create` npm package used by `npm create @glasskit.ai`. It is currently a WIP package that copies the Rokid Glasses starter app into a new project directory.

# Architecture

- `bin/create.js` is the plain JavaScript CLI entry point.
- `scripts/build-template.js` copies `../skills/glasskit/assets/rokid-hello-world` into `dist/template/rokid-hello-world` for local tests, npm packing, and publishing. Do not commit the generated `dist/` tree.
- `test/create.test.js` uses `node --test` and temporary directories to verify help/version output, project generation, and refusal to overwrite non-empty directories.
- `README.md` is a user-facing package doc.
- `PUBLISHING.md` is the package runbook for npm publishing.
  - npm releases are tag-triggered from the repository root workflow.

# Commands

- `npm ci`: install from the lockfile.
- `npm test`: rebuild the generated template and run the test suite.
- `npm run build`: refresh `dist/template/rokid-hello-world` from the canonical starter.
- `npm pack --dry-run`: inspect the publishable package contents.
- `npm pack --pack-destination /tmp/npm-package`: build a local tarball for smoke testing.
