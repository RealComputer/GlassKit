# Publishing GlassKit CLI

The PyPI project is `glasskit.ai`, and the installed command is `glasskit`. PyPI releases are tag-driven from GitHub Actions using PyPI Trusted Publishing, so no PyPI token should be stored in GitHub.

## One-Time Setup (Done)

The PyPI trusted publisher must match the release workflow exactly:

```text
PyPI project name: glasskit.ai
Owner: RealComputer
Repository name: GlassKit
Workflow filename: release.yml
Environment name: pypi
```

The GitHub environment named `pypi` requires review by `tash-2s` before the release job can run. The workflow references that environment so the PyPI OIDC claim includes the expected environment name.

## Release Flow

Run the local checks from this directory before tagging. The local Python version is pinned by `.python-version` and should match the release workflow.

```bash
uv sync --locked --dev
uv run python -c "import sys; assert sys.version_info[:2] == (3, 13), sys.version"
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

For a normal future release, bump the version, commit the version change, tag the commit with the PyPI package-specific tag format, and atomically push both the branch and tag:

```bash
uv version --bump patch
VERSION="$(uv version --short)"
git add pyproject.toml uv.lock
git commit -m "Release PyPI package glasskit.ai v${VERSION}"
git tag -a "pypi-glasskit-ai-v${VERSION}" -m "pypi-glasskit-ai-v${VERSION}"
git push --atomic origin main "pypi-glasskit-ai-v${VERSION}"
```

Pushing the `pypi-glasskit-ai-vX.Y.Z` tag runs `.github/workflows/release.yml`. The workflow checks that the tag matches `pyproject.toml`, runs type checks, tests, lint, formatting checks, source CLI help checks, builds wheel and sdist artifacts, smoke-tests both artifacts, publishes to PyPI with `uv publish --trusted-publishing always`, and creates a package-scoped GitHub Release with the built artifacts attached.

After pushing the release tag, open the GitHub Actions release run and approve the `pypi` deployment when GitHub asks for review.
