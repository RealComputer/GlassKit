import { AlertTriangle, FileCode2, Search, SlidersHorizontal } from "lucide-react";
import { useMemo } from "react";
import { useApp } from "../state/AppContext.tsx";

export function Sidebar() {
  const { state, dispatch, selectCase, selectTarget } = useApp();
  const workspace = state.selectedCaseId ? state.documents[state.selectedCaseId] : null;
  const caseNeedle = state.caseFilter.trim().toLowerCase();
  const targetNeedle = state.targetFilter.trim().toLowerCase();
  const filteredCases = useMemo(
    () =>
      (state.suite?.cases ?? []).filter(
        (item) =>
          !caseNeedle ||
          item.name.toLowerCase().includes(caseNeedle) ||
          item.description?.toLowerCase().includes(caseNeedle),
      ),
    [caseNeedle, state.suite?.cases],
  );
  const filteredTargets = useMemo(
    () =>
      (workspace?.document.targets ?? []).filter(
        (target) =>
          !targetNeedle ||
          target.id.toLowerCase().includes(targetNeedle) ||
          target.label?.toLowerCase().includes(targetNeedle),
      ),
    [targetNeedle, workspace?.document.targets],
  );

  return (
    <aside className="sidebar" aria-label="Eval navigation">
      <section className="sidebar-section cases-section">
        <div className="section-heading">
          <h2>Cases</h2>
          <span>{state.suite?.cases.length ?? 0}</span>
        </div>
        <label className="filter-input" htmlFor="case-filter">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">Filter cases</span>
          <input
            id="case-filter"
            type="search"
            value={state.caseFilter}
            placeholder="Filter cases"
            onChange={(event) => dispatch({ type: "SET_CASE_FILTER", value: event.target.value })}
          />
        </label>
        <div className="nav-list case-list">
          {filteredCases.map((item) => (
            <button
              key={item.id}
              type="button"
              className={`nav-row ${state.selectedCaseId === item.id ? "selected" : ""}`}
              onClick={() => void selectCase(item.id)}
              aria-current={state.selectedCaseId === item.id ? "page" : undefined}
            >
              <span className="nav-row-main">
                <span className="truncate" title={item.name}>
                  {item.name}
                </span>
                {item.status === "blocked" && (
                  <AlertTriangle
                    size={14}
                    className="danger"
                    aria-label="Case cannot be reviewed"
                  />
                )}
              </span>
              <span className="count-badge">
                {item.point_count === null ? "—" : item.point_count}
              </span>
              {item.description && (
                <span className="nav-description" title={item.description}>
                  {item.description}
                </span>
              )}
            </button>
          ))}
          {filteredCases.length === 0 && <p className="empty-inline">No matching cases</p>}
        </div>
      </section>

      <section className="sidebar-section targets-section">
        <div className="section-heading">
          <h2>Targets</h2>
          <span>{workspace?.document.targets.length ?? 0}</span>
        </div>
        <label className="filter-input" htmlFor="target-filter">
          <Search size={14} aria-hidden="true" />
          <span className="sr-only">Filter targets</span>
          <input
            id="target-filter"
            type="search"
            value={state.targetFilter}
            placeholder="Filter targets"
            disabled={!workspace}
            onChange={(event) => dispatch({ type: "SET_TARGET_FILTER", value: event.target.value })}
          />
        </label>
        <div className="nav-list target-list">
          {filteredTargets.map((target) => (
            <button
              key={target.id}
              type="button"
              className={`nav-row ${state.selectedTargetId === target.id ? "selected" : ""}`}
              onClick={() => void selectTarget(target.id)}
              aria-current={state.selectedTargetId === target.id ? "true" : undefined}
            >
              <span className="nav-row-main">
                <span className="truncate" title={target.label ?? target.id}>
                  {target.label ?? target.id}
                </span>
              </span>
              <span className="count-badge">{target.points.length}</span>
              {target.label && (
                <span className="nav-description mono" title={target.id}>
                  {target.id}
                </span>
              )}
            </button>
          ))}
          {workspace && filteredTargets.length === 0 && (
            <p className="empty-inline">No matching targets</p>
          )}
        </div>
      </section>

      <div className="sidebar-footer">
        {workspace?.document.description && (
          <details>
            <summary>Case details</summary>
            <p>{workspace.document.description}</p>
            <p className="muted mono path-text">
              {workspace.document.video?.display_path ?? "Video unavailable"}
            </p>
          </details>
        )}
        <button
          type="button"
          className="drawer-button"
          disabled={!workspace}
          onClick={() => dispatch({ type: "SET_SOURCE_DRAWER", value: "case" })}
        >
          <FileCode2 size={15} /> Case YAML
        </button>
        <button
          type="button"
          className="drawer-button"
          disabled={!state.suite?.config_source_yaml}
          onClick={() => dispatch({ type: "SET_SOURCE_DRAWER", value: "config" })}
        >
          <SlidersHorizontal size={15} /> Eval config
        </button>
      </div>
    </aside>
  );
}
