import { Fragment, useState } from "react";
import { ChevronDown, ChevronRight, MessageSquareText } from "lucide-react";
import type { ReviewSample } from "../api/types.ts";
import {
  groupConsecutiveSamples,
  regularSampleInterval,
  type ConsecutiveSampleGroup,
} from "../samples/grouping.ts";
import { useApp } from "../state/AppContext.tsx";
import { effectiveCompare, expectationSummary, formatSeconds } from "../utils/format.ts";

function SampleSettingsCells({ sample }: { sample: ReviewSample }) {
  return (
    <>
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
    </>
  );
}

function groupTimeSummary(group: ConsecutiveSampleGroup): string {
  const first = group.samples[0];
  const last = group.samples.at(-1) ?? first;
  const interval = regularSampleInterval(group.samples);
  const cadence = interval === null ? "" : ` · every ${Number(interval.toFixed(6))}s`;
  return `${formatSeconds(first.timestamp_s)}–${formatSeconds(last.timestamp_s)}${cadence} · ${group.samples.length} samples`;
}

export function SamplesTable() {
  const { state, selectSample, addSample } = useApp();
  const [expandedGroups, setExpandedGroups] = useState<Set<string>>(() => new Set());
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const target = workspace?.document.targets.find((item) => item.id === state.selectedTargetId);
  const groups = groupConsecutiveSamples(target?.samples ?? []);

  const select = (sample: ReviewSample) => {
    if (target) void selectSample(target.id, sample.id);
  };

  const toggleGroup = (groupId: string) => {
    setExpandedGroups((current) => {
      const next = new Set(current);
      if (next.has(groupId)) next.delete(groupId);
      else next.add(groupId);
      return next;
    });
  };

  return (
    <section className="samples-section" aria-label="Focused target samples">
      {groups.length ? (
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
              {groups.map((group) => {
                const first = group.samples[0];
                if (group.samples.length === 1) {
                  const selected = first.id === state.selectedSampleId;
                  return (
                    <tr
                      key={first.id}
                      className={selected ? "selected" : undefined}
                      onClick={() => select(first)}
                      onKeyDown={(event) => {
                        if (event.key === "Enter" || event.key === " ") {
                          event.preventDefault();
                          select(first);
                        }
                      }}
                      tabIndex={0}
                      aria-selected={selected}
                    >
                      <td className="mono">{formatSeconds(first.timestamp_s)}</td>
                      <SampleSettingsCells sample={first} />
                    </tr>
                  );
                }

                const expandedId = `${target?.id ?? ""}:${group.id}`;
                const expanded = expandedGroups.has(expandedId);
                const containsSelected = group.samples.some(
                  (sample) => sample.id === state.selectedSampleId,
                );
                const summary = groupTimeSummary(group);
                return (
                  <Fragment key={group.id}>
                    <tr
                      className={`sample-group-row${containsSelected ? " contains-selected" : ""}`}
                      onClick={() => toggleGroup(expandedId)}
                    >
                      <td className="sample-group-time" title={summary}>
                        <button
                          type="button"
                          className="sample-group-toggle"
                          aria-expanded={expanded}
                          aria-label={`${expanded ? "Collapse" : "Expand"} ${summary}`}
                        >
                          {expanded ? (
                            <ChevronDown size={14} aria-hidden="true" />
                          ) : (
                            <ChevronRight size={14} aria-hidden="true" />
                          )}
                          <span className="mono">{summary}</span>
                        </button>
                      </td>
                      <SampleSettingsCells sample={first} />
                    </tr>
                    {expanded &&
                      group.samples.map((sample) => {
                        const selected = sample.id === state.selectedSampleId;
                        return (
                          <tr
                            key={sample.id}
                            className={`sample-group-member${selected ? " selected" : ""}`}
                            onClick={() => select(sample)}
                            onKeyDown={(event) => {
                              if (event.key === "Enter" || event.key === " ") {
                                event.preventDefault();
                                select(sample);
                              }
                            }}
                            tabIndex={0}
                            aria-selected={selected}
                          >
                            <td className="mono">
                              <span className="sample-group-branch" aria-hidden="true">
                                ↳
                              </span>
                              {formatSeconds(sample.timestamp_s)}
                            </td>
                            <td colSpan={5} />
                          </tr>
                        );
                      })}
                  </Fragment>
                );
              })}
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
