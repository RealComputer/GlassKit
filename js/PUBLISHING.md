# Publishing @glasskit.ai/create

The npm package is `@glasskit.ai/create`, and the supported create command is `npm create @glasskit.ai`.

## One-Time Bootstrap (Done)

The first version was published manually because npm Trusted Publishing requires the package to already exist:

```bash
npm ci
npm test
npm pack --dry-run
npm publish --access public
```

Then configure npm Trusted Publishing for `@glasskit.ai/create`:

```bash
npm trust github @glasskit.ai/create \
  --repo RealComputer/GlassKit \
  --file release.yml \
  --env npm \
  --allow-publish
```

The GitHub environment is named `npm`, with `tash-2s` as the required reviewer and self-review allowed.

## Release Flow

Run the local checks from this directory before tagging:

```bash
npm ci
npm test
npm pack --dry-run
```

For a normal future release, bump the version without npm's default `vX.Y.Z` tag, commit the version change, create the package-specific tag, and atomically push both the branch and tag:

```bash
npm version patch --no-git-tag-version
VERSION="$(node -p "require('./package.json').version")"
git add package.json package-lock.json
git commit -m "Release @glasskit.ai/create v${VERSION}"
git tag -a "npm-glasskit-ai-create-v${VERSION}" -m "npm-glasskit-ai-create-v${VERSION}"
git push --atomic origin main "npm-glasskit-ai-create-v${VERSION}"
```

Pushing the `npm-glasskit-ai-create-vX.Y.Z` tag runs `.github/workflows/release.yml`. The workflow checks that the tag matches `package.json`, runs tests, builds the generated template, packs the npm artifact, smoke-tests the packed artifact, publishes to npm with Trusted Publishing/OIDC, and creates a package-scoped GitHub Release with the npm tarball attached.

After pushing the release tag, open the GitHub Actions release run and approve the `npm` deployment when GitHub asks for review.
