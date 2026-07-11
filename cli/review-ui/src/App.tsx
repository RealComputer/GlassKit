import { useEffect } from "react";
import { Header } from "./components/Header.tsx";
import { Inspector } from "./components/Inspector.tsx";
import { Overlays } from "./components/Overlays.tsx";
import { SamplesTable } from "./components/SamplesTable.tsx";
import { Sidebar } from "./components/Sidebar.tsx";
import { Timeline } from "./components/Timeline.tsx";
import { VideoPanel } from "./components/VideoPanel.tsx";
import { AppProvider, useApp } from "./state/AppContext.tsx";
import { shouldHandleShortcut } from "./utils/shortcuts.ts";
import "./App.css";

function ReviewApp() {
  const { state, selectSample, addSample, seek, reloadFromDisk } = useApp();
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const target = workspace?.document.targets.find((item) => item.id === state.selectedTargetId);
  const caseLoadError = state.selectedCaseId
    ? state.caseFileLoadErrors[state.selectedCaseId]
    : null;

  useEffect(() => {
    const onKeyDown = (event: KeyboardEvent) => {
      if (state.helpOpen || state.sourceDrawer) return;
      if (!shouldHandleShortcut(event)) return;
      const samples = [...(target?.samples ?? [])].sort(
        (left, right) => left.timestamp_s - right.timestamp_s,
      );
      const selectedIndex = samples.findIndex((sample) => sample.id === state.selectedSampleId);
      const selectRelative = (direction: -1 | 1) => {
        let sample = selectedIndex >= 0 ? samples[selectedIndex + direction] : undefined;
        if (!sample) {
          sample =
            direction < 0
              ? [...samples]
                  .reverse()
                  .find((item) => item.timestamp_s < state.video.currentTime - 1e-9)
              : samples.find((item) => item.timestamp_s > state.video.currentTime + 1e-9);
        }
        if (sample && target) void selectSample(target.id, sample.id);
      };
      switch (event.key) {
        case " ":
          event.preventDefault();
          {
            const video = document.querySelector("video");
            if (video && !video.error) {
              if (video.paused) void video.play().catch(() => undefined);
              else video.pause();
            }
          }
          break;
        case "[":
          event.preventDefault();
          selectRelative(-1);
          break;
        case "]":
          event.preventDefault();
          selectRelative(1);
          break;
        case "ArrowLeft":
          event.preventDefault();
          seek(Math.max(0, state.video.currentTime - (event.shiftKey ? 1 : 0.1)));
          break;
        case "ArrowRight":
          event.preventDefault();
          seek(
            Math.min(
              state.video.duration ?? Number.POSITIVE_INFINITY,
              state.video.currentTime + (event.shiftKey ? 1 : 0.1),
            ),
          );
          break;
        case "a":
        case "A":
          if (!event.shiftKey) {
            event.preventDefault();
            addSample();
          }
          break;
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [
    addSample,
    seek,
    selectSample,
    state.selectedSampleId,
    state.helpOpen,
    state.sourceDrawer,
    state.video.currentTime,
    state.video.duration,
    target,
  ]);

  if (state.evalDirectoryLoading) {
    return (
      <div className="loading-screen" role="status">
        <div className="loading-mark" />
        <strong>Loading eval directory…</strong>
      </div>
    );
  }

  if (state.evalDirectoryError && !state.evalDirectory) {
    return (
      <div className="fatal-screen" role="alert">
        <h1>Could not load the review UI</h1>
        <p>{state.evalDirectoryError}</p>
        <button type="button" className="button" onClick={() => location.reload()}>
          Reload
        </button>
      </div>
    );
  }

  return (
    <div className="app-shell">
      <Header />
      <div className="workspace-grid">
        <Sidebar />
        <main className="review-center">
          {caseLoadError && workspace && (
            <div className="issues-banner" role="alert">
              <span>
                <strong>Refresh failed:</strong> {caseLoadError}
              </span>
            </div>
          )}
          {workspace?.document.validation_issues.length ? (
            <div className="issues-banner" role="status">
              {workspace.document.validation_issues.map((issue) => (
                <span key={`${issue.code}-${issue.path ?? ""}`}>
                  <strong>{issue.repairable ? "Repair needed:" : "Issue:"}</strong> {issue.message}
                </span>
              ))}
            </div>
          ) : null}
          {state.selectedCaseId && !workspace && caseLoadError ? (
            <div className="empty-state case-load-error" role="alert">
              <strong>Could not load this case.</strong>
              <span>{caseLoadError}</span>
              <button type="button" className="button" onClick={() => void reloadFromDisk()}>
                Retry
              </button>
            </div>
          ) : state.selectedCaseId && !workspace ? (
            <div className="center-skeleton" role="status">
              <div />
              <div />
              <span>Loading case…</span>
            </div>
          ) : (
            <>
              <VideoPanel />
              <Timeline />
              <SamplesTable />
            </>
          )}
        </main>
        <Inspector />
      </div>
      <Overlays />
    </div>
  );
}

export default function App() {
  return (
    <AppProvider>
      <ReviewApp />
    </AppProvider>
  );
}
