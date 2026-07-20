# GlassKit Eval JSON Output

GlassKit Eval writes a machine-readable report when `glasskit eval run` receives `--output-json`. The report is written to the requested file, not stdout. Each JSON file represents one command invocation. By default, it has `repeat_count: 1` and one complete result set in `trials`.

For eval setup, adapter guidance, and the complete CLI reference, see the [GlassKit Eval README](README.md).

## Repeated-Run Example

The following example uses `glasskit eval run --repeat 2 --max-flaky-samples 0 --output-json eval/runs/results.json` so the report shows both per-trial results and cross-trial stability:

```json
{
  "schema_version": 1,
  "report_type": "eval_run",
  "eval_dir": "/absolute/path/to/eval",
  "cases": ["task-01"],
  "repeat_count": 2,
  "success": false,
  "checkpoint": {
    "path": "/workspace/eval/runs/checkpoints/run-20260720T143812Z-a1b2c3d4",
    "resumed": false,
    "resumable_adapter_errors": 0
  },
  "summary": {
    "trials": 2,
    "successful_trials": 2,
    "evaluated_samples": 1,
    "ignored_samples": 0,
    "evaluated_attempts": 2,
    "passed_attempts": 1,
    "failed_attempts": 1,
    "error_attempts": 0,
    "attempt_pass_rate": 0.5,
    "minimum_trial_pass_rate": 0.0,
    "mean_trial_pass_rate": 0.5,
    "maximum_trial_pass_rate": 1.0,
    "consistently_passed_samples": 0,
    "consistently_failed_samples": 0,
    "flaky_samples": 1,
    "error_samples": 0,
    "duration_seconds": 0.84,
    "evaluation_timing_mode": "individual",
    "average_evaluation_seconds_per_attempt": 0.3,
    "throughput_attempts_per_second": 2.38
  },
  "gates": [
    {
      "name": "max_flaky_samples",
      "passed": false,
      "message": "1 flaky sample (gate: <= 0)"
    }
  ],
  "trials": [
    {
      "trial": 1,
      "success": true,
      "summary": {
        "evaluated": 1,
        "passed": 1,
        "failed": 0,
        "errors": 0,
        "ignored": 0,
        "pass_rate": 1.0,
        "duration_seconds": 0.4,
        "evaluation_timing_mode": "individual",
        "average_evaluation_seconds_per_sample": 0.3,
        "throughput_samples_per_second": 2.5
      },
      "gates": [
        {
          "name": "adapter_errors",
          "passed": true,
          "message": "no adapter/comparison errors"
        }
      ],
      "results": [
        {
          "case": "task-01",
          "target": "step_1",
          "target_label": "Step 1",
          "sample_index": 0,
          "timestamp_s": 0.0,
          "status": "passed",
          "expected": true,
          "observed": {"matches": true},
          "observed_value": true,
          "compare_mode": "exact",
          "field": "matches",
          "reason": "matched",
          "source": "at",
          "evaluation_duration_seconds": 0.3,
          "evaluation_timing_mode": "individual",
          "artifact_image": null,
          "artifact_json": null
        }
      ]
    },
    {
      "trial": 2,
      "success": true,
      "summary": {
        "evaluated": 1,
        "passed": 0,
        "failed": 1,
        "errors": 0,
        "ignored": 0,
        "pass_rate": 0.0,
        "duration_seconds": 0.4,
        "evaluation_timing_mode": "individual",
        "average_evaluation_seconds_per_sample": 0.3,
        "throughput_samples_per_second": 2.5
      },
      "gates": [
        {
          "name": "adapter_errors",
          "passed": true,
          "message": "no adapter/comparison errors"
        }
      ],
      "results": [
        {
          "case": "task-01",
          "target": "step_1",
          "target_label": "Step 1",
          "sample_index": 0,
          "timestamp_s": 0.0,
          "status": "failed",
          "expected": true,
          "observed": {"matches": false},
          "observed_value": false,
          "compare_mode": "exact",
          "field": "matches",
          "reason": "expected exact match",
          "source": "at",
          "evaluation_duration_seconds": 0.3,
          "evaluation_timing_mode": "individual",
          "artifact_image": null,
          "artifact_json": null
        }
      ]
    }
  ],
  "stability": [
    {
      "case": "task-01",
      "target": "step_1",
      "target_label": "Step 1",
      "sample_index": 0,
      "timestamp_s": 0.0,
      "expected": true,
      "source": "at",
      "statuses": ["passed", "failed"],
      "evaluated": 2,
      "passed": 1,
      "failed": 1,
      "errors": 0,
      "pass_rate": 0.5,
      "ignored": false,
      "consistently_passed": false,
      "consistently_failed": false,
      "flaky": true
    }
  ]
}
```

## Report Structure

The `trials` array is the report's uniform representation for complete executions. A default run has one entry; with `--repeat`, each repetition adds an entry identified by its `trial` number. Root `gates` contains run-wide stability gates, while each entry in `trials` contains its own quality gates and complete sample results. The `stability` array follows the deterministic result order and records each logical sample's status sequence. Ignored samples appear in every result set with status `ignored`, but root logical-sample counts include each ignored sample only once; attempts, pass rates, timing, throughput, quality gates, and stability gates exclude ignored outcomes.

The root `checkpoint` object identifies the durable checkpoint associated with the logical run. `resumed` is true when this report was produced by `glasskit eval run --resume`; `resumable_adapter_errors` counts adapter-error result slots that another manual resume can retry without reevaluating completed samples. Ordinary failed comparisons and comparison-error results are completed outcomes and are not included in that count. A report normally points to a complete checkpoint, while a `--keep-going` report with adapter errors points to an incomplete checkpoint that retains the attempt history.
