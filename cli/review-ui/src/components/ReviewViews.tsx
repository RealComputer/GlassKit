import { useState, type KeyboardEvent } from "react";
import { useApp } from "../state/AppContext.tsx";
import { SamplesTable } from "./SamplesTable.tsx";
import { Timeline } from "./Timeline.tsx";

type ReviewView = "timeline" | "samples";

const reviewViews: ReviewView[] = ["timeline", "samples"];

export function ReviewViews() {
  const { state } = useApp();
  const [activeView, setActiveView] = useState<ReviewView>("timeline");
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const targets = workspace?.document.targets ?? [];
  const target = targets.find((item) => item.id === state.selectedTargetId);
  const timelineCount = targets.reduce((total, item) => total + item.samples.length, 0);

  const handleTabKeyDown = (event: KeyboardEvent<HTMLButtonElement>, view: ReviewView) => {
    const index = reviewViews.indexOf(view);
    const nextView =
      event.key === "ArrowRight"
        ? reviewViews[(index + 1) % reviewViews.length]
        : event.key === "ArrowLeft"
          ? reviewViews[(index - 1 + reviewViews.length) % reviewViews.length]
          : event.key === "Home"
            ? reviewViews[0]
            : event.key === "End"
              ? reviewViews.at(-1)
              : null;
    if (!nextView) return;
    event.preventDefault();
    setActiveView(nextView);
    requestAnimationFrame(() => document.getElementById(`${nextView}-view-tab`)?.focus());
  };

  return (
    <section className="review-views" aria-label="Timeline and samples">
      <div className="review-view-tabs" role="tablist" aria-label="Review view">
        <button
          id="timeline-view-tab"
          type="button"
          role="tab"
          aria-selected={activeView === "timeline"}
          aria-controls="timeline-view-panel"
          tabIndex={activeView === "timeline" ? 0 : -1}
          onClick={() => setActiveView("timeline")}
          onKeyDown={(event) => handleTabKeyDown(event, "timeline")}
        >
          Timeline <span>{timelineCount}</span>
        </button>
        <button
          id="samples-view-tab"
          type="button"
          role="tab"
          aria-selected={activeView === "samples"}
          aria-controls="samples-view-panel"
          tabIndex={activeView === "samples" ? 0 : -1}
          onClick={() => setActiveView("samples")}
          onKeyDown={(event) => handleTabKeyDown(event, "samples")}
        >
          Samples <span>{target?.samples.length ?? 0}</span>
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
