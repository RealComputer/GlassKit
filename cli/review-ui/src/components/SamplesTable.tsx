import { MessageSquareText } from "lucide-react";
import { useApp } from "../state/AppContext.tsx";
import { effectiveCompare, expectationSummary, formatSeconds } from "../utils/format.ts";

export function SamplesTable() {
  const { state, selectSample, addSample } = useApp();
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const target = workspace?.document.targets.find((item) => item.id === state.selectedTargetId);
  const samples = [...(target?.samples ?? [])].sort(
    (left, right) => left.timestamp_s - right.timestamp_s,
  );
  return (
    <section className="samples-section" aria-label="Focused target samples">
      <div className="section-title table-title">
        <h2>Samples</h2>
        <span>{target?.label ?? target?.id ?? "Select a target"}</span>
      </div>
      {samples.length ? (
        <div className="table-scroll">
          <table>
            <thead>
              <tr>
                <th>Time</th>
                <th>Expectation</th>
                <th>Field</th>
                <th>Compare</th>
                <th>Tolerance</th>
                <th aria-label="Comment">Note</th>
              </tr>
            </thead>
            <tbody>
              {samples.map((sample) => (
                <tr
                  key={sample.id}
                  className={sample.id === state.selectedSampleId ? "selected" : undefined}
                  onClick={() => {
                    if (target) void selectSample(target.id, sample.id);
                  }}
                  onKeyDown={(event) => {
                    if ((event.key === "Enter" || event.key === " ") && target) {
                      event.preventDefault();
                      void selectSample(target.id, sample.id);
                    }
                  }}
                  tabIndex={0}
                  aria-selected={sample.id === state.selectedSampleId}
                >
                  <td className="mono">{formatSeconds(sample.timestamp_s)}</td>
                  <td className="expect-cell" title={sample.expect_json}>
                    <span className="type-chip">{sample.expect_type}</span>
                    {expectationSummary(sample)}
                  </td>
                  <td className="mono truncate-cell" title={sample.field ?? ""}>
                    {sample.field ?? "—"}
                  </td>
                  <td>{effectiveCompare(sample)}</td>
                  <td className="mono">{sample.compare.tolerance ?? "—"}</td>
                  <td>
                    {sample.comment ? (
                      <MessageSquareText size={15} aria-label={`Comment: ${sample.comment}`} />
                    ) : (
                      "—"
                    )}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      ) : target ? (
        <div className="empty-state compact">
          <strong>This target has no samples.</strong>
          <span>Add its first sample at the current video time.</span>
          <button
            type="button"
            className="button primary-button"
            onClick={addSample}
            disabled={
              !workspace?.document.editing_enabled || Object.keys(workspace.formErrors).length > 0
            }
          >
            Add first sample
          </button>
        </div>
      ) : (
        <div className="empty-state compact">Select a target to inspect samples.</div>
      )}
    </section>
  );
}
