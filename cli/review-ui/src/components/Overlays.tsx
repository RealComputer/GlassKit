import { X } from "lucide-react";
import { useEffect, useRef } from "react";
import { useApp } from "../state/AppContext.tsx";

export function Overlays() {
  const { state, dispatch } = useApp();
  const workspace = state.selectedCaseId ? state.documents[state.selectedCaseId] : null;
  const drawerText =
    state.sourceDrawer === "case"
      ? workspace?.acceptedDocument.source_yaml
      : state.sourceDrawer === "config"
        ? state.suite?.config_source_yaml
        : null;
  const sourceRef = useRef<HTMLElement>(null);
  const helpRef = useRef<HTMLElement>(null);
  const overlayOpen = Boolean(state.sourceDrawer || state.helpOpen);

  useEffect(() => {
    if (!overlayOpen) return;
    const opener = document.activeElement instanceof HTMLElement ? document.activeElement : null;
    const frame = requestAnimationFrame(() => {
      const root = sourceRef.current ?? helpRef.current;
      root?.querySelector<HTMLElement>("button, [href], input, select, textarea")?.focus();
    });
    return () => {
      cancelAnimationFrame(frame);
      if (opener?.isConnected) opener.focus();
    };
  }, [overlayOpen]);

  useEffect(() => {
    if (!state.sourceDrawer && !state.helpOpen) return;
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        event.preventDefault();
        dispatch({ type: "SET_SOURCE_DRAWER", value: null });
        dispatch({ type: "SET_HELP_OPEN", value: false });
      } else if (event.key === "Tab") {
        const root = sourceRef.current ?? helpRef.current;
        if (!root) return;
        const focusable = Array.from(
          root.querySelectorAll<HTMLElement>(
            'button:not(:disabled), [href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex="-1"])',
          ),
        );
        if (focusable.length === 0) {
          event.preventDefault();
          root.focus();
          return;
        }
        const current = document.activeElement;
        const index = focusable.indexOf(current as HTMLElement);
        const nextIndex = event.shiftKey
          ? index <= 0
            ? focusable.length - 1
            : index - 1
          : index < 0 || index === focusable.length - 1
            ? 0
            : index + 1;
        event.preventDefault();
        focusable[nextIndex].focus();
      }
    };
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [dispatch, state.helpOpen, state.sourceDrawer]);

  return (
    <>
      {state.sourceDrawer && (
        <div className="overlay-backdrop">
          <aside
            ref={sourceRef}
            className="source-drawer"
            role="dialog"
            aria-modal="true"
            aria-label={`${state.sourceDrawer} YAML`}
            tabIndex={-1}
          >
            <div className="drawer-heading">
              <div>
                <h2>{state.sourceDrawer === "case" ? "Case YAML" : "Eval config"}</h2>
                {state.sourceDrawer === "case" && workspace?.dirtyTargetIds.length ? (
                  <span>Last accepted source; local drafts are not shown yet.</span>
                ) : (
                  <span>Read-only source</span>
                )}
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close source drawer"
                onClick={() => dispatch({ type: "SET_SOURCE_DRAWER", value: null })}
              >
                <X size={18} />
              </button>
            </div>
            <pre>{drawerText ?? "No source file is available."}</pre>
          </aside>
        </div>
      )}
      {state.helpOpen && (
        <div className="modal-backdrop" role="presentation">
          <section
            ref={helpRef}
            className="shortcuts-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="shortcuts-title"
            tabIndex={-1}
          >
            <div className="drawer-heading">
              <h2 id="shortcuts-title">Keyboard shortcuts</h2>
              <button
                type="button"
                className="icon-button"
                aria-label="Close keyboard shortcuts"
                onClick={() => dispatch({ type: "SET_HELP_OPEN", value: false })}
              >
                <X size={18} />
              </button>
            </div>
            <dl className="shortcut-list">
              <div>
                <dt>
                  <kbd>Space</kbd>
                </dt>
                <dd>Play or pause</dd>
              </div>
              <div>
                <dt>
                  <kbd>[</kbd> / <kbd>]</kbd>
                </dt>
                <dd>Previous / next point</dd>
              </div>
              <div>
                <dt>
                  <kbd>←</kbd> / <kbd>→</kbd>
                </dt>
                <dd>Nudge playhead 0.1 seconds</dd>
              </div>
              <div>
                <dt>
                  <kbd>Shift</kbd> + <kbd>←</kbd> / <kbd>→</kbd>
                </dt>
                <dd>Nudge playhead 1 second</dd>
              </div>
              <div>
                <dt>
                  <kbd>A</kbd>
                </dt>
                <dd>Add point at playhead</dd>
              </div>
            </dl>
          </section>
        </div>
      )}
      {state.toast && (
        <div className="toast" role="status">
          {state.toast}
        </div>
      )}
    </>
  );
}
