import { MessageSquareText } from "lucide-react";
import { useApp } from "../state/AppContext.tsx";
import { effectiveCompare, expectationSummary, formatSeconds } from "../utils/format.ts";

export function SamplesTable() {
  const { state, selectPoint, addPoint } = useApp();
  const workspace = state.selectedCaseId ? state.documents[state.selectedCaseId] : null;
  const target = workspace?.document.targets.find((item) => item.id === state.selectedTargetId);
  const points = [...(target?.points ?? [])].sort(
    (left, right) => left.timestamp_s - right.timestamp_s,
  );
  return (
    <section className="samples-section" aria-label="Focused target samples">
      <div className="section-title table-title">
        <h2>Samples</h2>
        <span>{target?.label ?? target?.id ?? "Select a target"}</span>
      </div>
      {points.length ? (
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
              {points.map((point) => (
                <tr
                  key={point.id}
                  className={point.id === state.selectedPointId ? "selected" : undefined}
                  onClick={() => {
                    if (target) void selectPoint(target.id, point.id);
                  }}
                  onKeyDown={(event) => {
                    if ((event.key === "Enter" || event.key === " ") && target) {
                      event.preventDefault();
                      void selectPoint(target.id, point.id);
                    }
                  }}
                  tabIndex={0}
                  aria-selected={point.id === state.selectedPointId}
                >
                  <td className="mono">{formatSeconds(point.timestamp_s)}</td>
                  <td className="expect-cell" title={point.expect_json}>
                    <span className="type-chip">{point.expect_type}</span>
                    {expectationSummary(point)}
                  </td>
                  <td className="mono truncate-cell" title={point.field ?? ""}>
                    {point.field ?? "—"}
                  </td>
                  <td>{effectiveCompare(point)}</td>
                  <td className="mono">{point.compare.tolerance ?? "—"}</td>
                  <td>
                    {point.comment ? (
                      <MessageSquareText size={15} aria-label={`Comment: ${point.comment}`} />
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
          <span>Add its first point at the current playhead.</span>
          <button
            type="button"
            className="button primary-button"
            onClick={addPoint}
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
