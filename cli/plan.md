# Future Work

This file tracks remaining and future work for the `glasskit eval` recorded-video evaluator.

## Priorities

- Decide the storage policy for realistic eval suites before committing any real recordings. Use external storage, Git LFS, or artifact buckets only after making an explicit privacy and repository-size decision.
  - Document any future storage location for realistic eval suites once that policy exists.
- Add clip-level evaluation support only when an app needs temporal model observations. This should be an optional protocol and schema extension rather than changing the frame-sample adapter contract.
- Add adapters and eval suites for `../examples/rokid-overshoot-openai-realtime` or `../examples/rokid-rfdetr` only when there is a concrete need. The core CLI should stay app-agnostic and continue to compare JSON-like observations through fields and comparison modes.
