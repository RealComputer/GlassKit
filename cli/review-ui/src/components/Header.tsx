import { CircleAlert, CircleHelp, RefreshCw, RotateCcw } from "lucide-react";
import { useApp } from "../state/AppContext.tsx";
import { formatTime } from "../utils/format.ts";

const labels = {
  saved: "Saved",
  unsaved: "Unsaved",
  saving: "Saving",
  repairs: "Complete repairs",
  invalid: "Fix errors",
  failed: "Save failed",
} as const;

export function Header() {
  const { state, dispatch, retrySave, reloadFromDisk } = useApp();
  const workspace = state.selectedCaseId ? state.documents[state.selectedCaseId] : null;
  const currentCase = workspace?.document;
  const phase = workspace?.savePhase ?? "saved";
  return (
    <header className="app-header">
      <div className="brand">GlassKit Eval Review</div>
      <div className="header-context" aria-live="polite">
        {currentCase ? (
          <>
            <strong title={currentCase.id}>{currentCase.name}</strong>
            {state.selectedTargetId && (
              <span className="header-target" title={state.selectedTargetId}>
                / {state.selectedTargetId}
              </span>
            )}
          </>
        ) : (
          <span>No case selected</span>
        )}
      </div>
      <div className="header-time mono">
        {formatTime(state.video.currentTime)} /{" "}
        {state.video.duration === null ? "--:--.---" : formatTime(state.video.duration)}
      </div>
      <button
        type="button"
        className="icon-button header-help"
        aria-label="Show keyboard shortcuts"
        title="Keyboard shortcuts"
        onClick={() => dispatch({ type: "SET_HELP_OPEN", value: true })}
      >
        <CircleHelp size={17} />
      </button>
      <div className={`save-status save-${phase}`} role="status">
        {phase === "failed" || phase === "invalid" ? (
          <CircleAlert size={15} aria-hidden="true" />
        ) : phase === "saving" ? (
          <RefreshCw size={15} className="spin" aria-hidden="true" />
        ) : null}
        <span>{labels[phase]}</span>
        {phase === "failed" && (
          <span className="save-actions">
            <button type="button" className="text-button" onClick={retrySave}>
              Retry
            </button>
            <button
              type="button"
              className="text-button"
              onClick={() => void reloadFromDisk()}
              aria-label="Reload case from disk and discard drafts"
              title="Reload from disk"
            >
              <RotateCcw size={13} /> Reload
            </button>
          </span>
        )}
        {(phase === "repairs" || phase === "invalid") && (
          <button
            type="button"
            className="text-button discard-button"
            onClick={() => void reloadFromDisk()}
            aria-label="Discard local drafts and reload this case from disk"
            title="Discard drafts and reload from disk"
          >
            <RotateCcw size={13} /> Discard drafts
          </button>
        )}
      </div>
    </header>
  );
}
