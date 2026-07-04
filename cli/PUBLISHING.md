# Publishing GlassKit CLI

The PyPI project is `glasskit.ai`, and the installed command is `glasskit`. Releases are tag-driven from GitHub Actions using PyPI Trusted Publishing, so no PyPI token should be stored in GitHub.

## One-Time Setup

The PyPI trusted publisher must match the release workflow exactly:

```text
PyPI project name: glasskit.ai
Owner: RealComputer
Repository name: GlassKit
Workflow filename: release.yml
Environment name: pypi
```

The GitHub environment named `pypi` requires review by `tash-2s` before the release job can run. Self-review is allowed for now because this repo has a solo maintainer. The workflow references that environment so the PyPI OIDC claim includes the expected environment name.

## Release Flow

Run the local checks from this directory before tagging:

```bash
uv sync --locked --dev
uv run ty check
uv run pytest
uv run ruff check --fix
uv run ruff format
uv run glasskit --help
uv run glasskit eval --help
uv build --no-sources --clear
uv run --isolated --no-project --with dist/*.whl glasskit --help
uv run --isolated --no-project --with dist/*.tar.gz glasskit --help
```

For a normal future release, bump the version, commit the version change, tag the commit, and push both the branch and tag:

```bash
uv version --bump patch
VERSION="$(uv version --short)"
git add pyproject.toml uv.lock
git commit -m "Release v${VERSION}"
git tag -a "v${VERSION}" -m "v${VERSION}"
git push origin main
git push origin "v${VERSION}"
```

Pushing the tag runs `.github/workflows/release.yml`. The workflow checks that the tag matches `pyproject.toml`, runs type checks, tests, lint, formatting checks, source CLI help checks, builds wheel and sdist artifacts, smoke-tests both artifacts, publishes to PyPI with `uv publish --trusted-publishing always`, and creates a GitHub Release with the built artifacts attached.

After pushing the release tag, open the GitHub Actions release run and approve the `pypi` deployment when GitHub asks for review. If the PyPI publish fails because the trusted publisher does not match, check the PyPI project name, owner, repository, workflow filename, and environment name listed above.
