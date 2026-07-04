# Publishing @glasskit.ai/create

The npm package is `@glasskit.ai/create`, and the supported create command is `npm create @glasskit.ai`. This package is intentionally WIP for the first release.

## One-Time Bootstrap

If the npm package does not exist yet, publish the first version manually from this directory because npm Trusted Publishing is configured from an existing package's settings:

```bash
npm ci
npm test
npm pack --dry-run
npm publish --access public
```

Then configure npm Trusted Publishing on npmjs.com for `@glasskit.ai/create`:

```text
Owner: RealComputer
Repository name: GlassKit
Workflow filename: release.yml
Environment name: npm
Allowed action: npm publish
```

Create a GitHub environment named `npm`. A required reviewer is optional but recommended.

## Release Flow

Run the local checks from this directory before tagging:

```bash
npm ci
npm test
npm pack --dry-run
```

For a normal future release, bump the version, commit the version change, tag the commit with the npm package-specific tag format, and push both the branch and tag:

```bash
npm version patch -m "Release @glasskit.ai/create %s"
VERSION="$(node -p "require('./package.json').version")"
git push origin main
git push origin "npm-glasskit-ai-create-v${VERSION}"
```

Pushing the `npm-glasskit-ai-create-vX.Y.Z` tag runs `.github/workflows/release.yml`. The workflow checks that the tag matches `package.json`, runs tests, builds the generated template, packs the npm artifact, smoke-tests the packed artifact, publishes to npm with Trusted Publishing/OIDC, and creates a package-scoped GitHub Release with the npm tarball attached.
