import { useState } from "react";
import { useApp } from "../state/AppContext.tsx";
import { SamplesTable } from "./SamplesTable.tsx";
import { Timeline } from "./Timeline.tsx";

type ReviewView = "timeline" | "samples";

export function ReviewViews() {
  const { state } = useApp();
  const [activeView, setActiveView] = useState<ReviewView>("timeline");
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const target = workspace?.document.targets.find((item) => item.id === state.selectedTargetId);

  return (
    <section className="review-views" aria-label="Timeline and samples">
      <div className="review-view-tabs" role="tablist" aria-label="Review view">
        <button
          id="timeline-view-tab"
          type="button"
          role="tab"
          aria-selected={activeView === "timeline"}
          aria-controls="timeline-view-panel"
          onClick={() => setActiveView("timeline")}
          onPointerUp={(event) => event.currentTarget.blur()}
        >
          Timeline
        </button>
        <button
          id="samples-view-tab"
          type="button"
          role="tab"
          aria-selected={activeView === "samples"}
          aria-controls="samples-view-panel"
          onClick={() => setActiveView("samples")}
          onPointerUp={(event) => event.currentTarget.blur()}
        >
          Samples
        </button>
        {activeView === "samples" && (
          <span className="review-view-context">
            {target?.label ?? target?.id ?? "Select a target"}
          </span>
        )}
      </div>
      {activeView === "timeline" ? (
        <div
          id="timeline-view-panel"
          className="review-view-panel"
          role="tabpanel"
          aria-labelledby="timeline-view-tab"
        >
          <Timeline />
        </div>
      ) : (
        <div
          id="samples-view-panel"
          className="review-view-panel"
          role="tabpanel"
          aria-labelledby="samples-view-tab"
        >
          <SamplesTable />
        </div>
      )}
    </section>
  );
}
