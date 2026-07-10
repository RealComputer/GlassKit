import { X } from 'lucide-react'
import { useEffect } from 'react'
import { useApp } from '../state/AppContext.tsx'

export function Overlays() {
  const { state, dispatch } = useApp()
  const workspace = state.selectedCaseId
    ? state.documents[state.selectedCaseId]
    : null
  const drawerText =
    state.sourceDrawer === 'case'
      ? workspace?.acceptedDocument.source_yaml
      : state.sourceDrawer === 'config'
        ? state.suite?.config_source_yaml
        : null

  useEffect(() => {
    if (!state.sourceDrawer && !state.helpOpen) return
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key === 'Escape') {
        dispatch({ type: 'SET_SOURCE_DRAWER', value: null })
        dispatch({ type: 'SET_HELP_OPEN', value: false })
      }
    }
    window.addEventListener('keydown', onKeyDown)
    return () => window.removeEventListener('keydown', onKeyDown)
  }, [dispatch, state.helpOpen, state.sourceDrawer])

  return (
    <>
      {state.sourceDrawer && (
        <div className="overlay-backdrop">
          <aside className="source-drawer" aria-label={`${state.sourceDrawer} YAML`}>
            <div className="drawer-heading">
              <div>
                <h2>{state.sourceDrawer === 'case' ? 'Case YAML' : 'Eval config'}</h2>
                {state.sourceDrawer === 'case' && workspace?.dirtyTargetIds.length ? (
                  <span>Last accepted source; local drafts are not shown yet.</span>
                ) : (
                  <span>Read-only source</span>
                )}
              </div>
              <button
                type="button"
                className="icon-button"
                aria-label="Close source drawer"
                onClick={() =>
                  dispatch({ type: 'SET_SOURCE_DRAWER', value: null })
                }
              >
                <X size={18} />
              </button>
            </div>
            <pre>{drawerText ?? 'No source file is available.'}</pre>
          </aside>
        </div>
      )}
      {state.helpOpen && (
        <div className="modal-backdrop" role="presentation">
          <section
            className="shortcuts-dialog"
            role="dialog"
            aria-modal="true"
            aria-labelledby="shortcuts-title"
          >
            <div className="drawer-heading">
              <h2 id="shortcuts-title">Keyboard shortcuts</h2>
              <button
                type="button"
                className="icon-button"
                aria-label="Close keyboard shortcuts"
                autoFocus
                onClick={() =>
                  dispatch({ type: 'SET_HELP_OPEN', value: false })
                }
              >
                <X size={18} />
              </button>
            </div>
            <dl className="shortcut-list">
              <div><dt><kbd>Space</kbd></dt><dd>Play or pause</dd></div>
              <div><dt><kbd>[</kbd> / <kbd>]</kbd></dt><dd>Previous / next point</dd></div>
              <div><dt><kbd>←</kbd> / <kbd>→</kbd></dt><dd>Nudge playhead 0.1 seconds</dd></div>
              <div><dt><kbd>Shift</kbd> + <kbd>←</kbd> / <kbd>→</kbd></dt><dd>Nudge playhead 1 second</dd></div>
              <div><dt><kbd>A</kbd></dt><dd>Add point at playhead</dd></div>
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
  )
}
