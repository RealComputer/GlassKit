# GlassKit CLI Eval Future Work

This file tracks remaining and future work for the `gk eval` recorded-video evaluator. Implemented design notes and completed phases have been removed; current user-facing behavior belongs in `cli/README.md`, and contributor guidance belongs in `cli/AGENTS.md`.

## Priorities

- Prepare the `gk` package for publication by confirming package metadata, release workflow, versioning policy, and PyPI name availability before the first public release.
- Decide the storage policy for realistic eval suites before committing any real recordings. Use external storage, Git LFS, or artifact buckets only after making an explicit privacy and repository-size decision.
- Profile long sparse videos, such as 30 minute recordings with a small number of labeled timestamps. If sequential decoding is materially slow, add sparse PyAV seeking while preserving timestamp normalization to clip start and nearest-frame selection correctness.
- Add clip-level evaluation support only when an app needs temporal model observations. This should be an optional protocol and schema extension rather than changing the frame-sample adapter contract.
- Add explicit label-review affordances if manual labeling becomes painful, such as note fields, optional ignored regions, or a timeline helper. Keep unlabeled gaps as the default way to skip transition or ambiguous windows.
- Add a separate workflow/session replay layer if app state-machine behavior needs regression coverage. Keep it separate from `gk eval` frame observation quality unless there is a concrete integration design.
- Add adapters and eval suites for `rokid-overshoot-openai-realtime` or `rokid-rfdetr` only when there is a concrete need. The core CLI should stay app-agnostic and continue to compare JSON-like observations through fields and comparison modes.

## Test Backlog

- Keep real Origami/Overshoot eval runs as explicit local smoke checks, not default package tests, unless they are guarded by required environment variables and skipped by default.
- Add regression coverage whenever video seeking is introduced, especially for non-zero start timestamps, WebM/container duration fallbacks, and sparse samples near keyframe boundaries.

## Documentation Backlog

- Document any future storage location for realistic eval suites once that policy exists.
- Add release notes for the first published package, including the adapter contract and the supported eval-suite schema version.
