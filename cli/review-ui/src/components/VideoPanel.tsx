import {
  CirclePlus,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  StepBack,
  StepForward,
} from 'lucide-react'
import { useEffect, useMemo, useRef, useState } from 'react'
import { useApp } from '../state/AppContext.tsx'
import { formatSeconds } from '../utils/format.ts'
import { PreciseVideoSeeker } from '../video/PreciseVideoSeeker.ts'

export function VideoPanel() {
  const {
    state,
    dispatch,
    selectPoint,
    addPoint,
    seek,
  } = useApp()
  const videoRef = useRef<HTMLVideoElement>(null)
  const timeInputRef = useRef<HTMLInputElement>(null)
  const seekerRef = useRef<PreciseVideoSeeker | null>(null)
  const skipNextTimeBlur = useRef(false)
  const [timeDraft, setTimeDraft] = useState('0.000')
  const workspace = state.selectedCaseId
    ? state.documents[state.selectedCaseId]
    : null
  const document = workspace?.document
  const target = document?.targets.find(
    (item) => item.id === state.selectedTargetId,
  )
  const hasFormErrors = Boolean(
    workspace && Object.keys(workspace.formErrors).length > 0,
  )
  const points = useMemo(
    () => [...(target?.points ?? [])].sort((a, b) => a.timestamp_s - b.timestamp_s),
    [target?.points],
  )

  useEffect(() => {
    if (globalThis.document.activeElement !== timeInputRef.current) {
      setTimeDraft(state.video.currentTime.toFixed(3))
    }
  }, [state.video.currentTime])

  useEffect(() => {
    const video = videoRef.current
    if (!video) return
    const seeker = new PreciseVideoSeeker(video, (preview) => {
      dispatch({
        type: 'VIDEO_PATCH',
        patch: {
          previewStatus: preview.status,
          shownFrameTime: preview.shownFrameTime,
          previewMessage: preview.message,
        },
      })
    })
    seekerRef.current = seeker
    return () => {
      seeker.cancel()
      seekerRef.current = null
    }
  }, [dispatch, document?.video?.url, state.video.mediaGeneration])

  useEffect(() => {
    if (state.video.seekRequest.generation === 0) return
    const video = videoRef.current
    if (!document?.video?.url || !video || !seekerRef.current) {
      dispatch({
        type: 'VIDEO_PATCH',
        patch: {
          previewStatus: 'unavailable',
          shownFrameTime: null,
          previewMessage: 'No browser-playable video is available for this case.',
        },
      })
      return
    }
    video.pause()
    seekerRef.current.seek(state.video.seekRequest.time)
  }, [
    dispatch,
    document?.video?.url,
    state.video.mediaGeneration,
    state.video.seekRequest.generation,
    state.video.seekRequest.time,
  ])

  const relativeIndex = () => {
    if (state.selectedPointId) {
      const index = points.findIndex((point) => point.id === state.selectedPointId)
      if (index >= 0) return index
    }
    return points.findIndex((point) => point.timestamp_s >= state.video.currentTime)
  }

  const previous = () => {
    const selectedIndex = state.selectedPointId
      ? points.findIndex((point) => point.id === state.selectedPointId)
      : -1
    const point =
      selectedIndex >= 0
        ? points[selectedIndex - 1]
        : [...points]
            .reverse()
            .find((item) => item.timestamp_s < state.video.currentTime - 1e-9)
    if (point && target) void selectPoint(target.id, point.id)
  }
  const next = () => {
    const index = relativeIndex()
    const point = state.selectedPointId
      ? points[index + 1]
      : points.find((item) => item.timestamp_s > state.video.currentTime + 1e-9)
    if (point && target) void selectPoint(target.id, point.id)
  }
  const hasPrevious = state.selectedPointId
    ? points.findIndex((point) => point.id === state.selectedPointId) > 0
    : points.some((point) => point.timestamp_s < state.video.currentTime - 1e-9)
  const selectedIndex = state.selectedPointId
    ? points.findIndex((point) => point.id === state.selectedPointId)
    : -1
  const hasNext = state.selectedPointId
    ? selectedIndex >= 0 && selectedIndex < points.length - 1
    : points.some((point) => point.timestamp_s > state.video.currentTime + 1e-9)

  const togglePlay = () => {
    const video = videoRef.current
    if (!video) return
    if (video.paused) {
      void video.play().catch(() =>
        dispatch({
          type: 'VIDEO_PATCH',
          patch: {
            previewStatus: 'unavailable',
            previewMessage: 'This browser cannot play the video codec.',
          },
        }),
      )
    }
    else video.pause()
  }
  const nudge = (delta: number) =>
    seek(
      Math.min(
        state.video.duration ?? Number.POSITIVE_INFINITY,
        Math.max(0, state.video.currentTime + delta),
      ),
    )
  const commitTimeDraft = () => {
    const parsed = Number(timeDraft)
    if (!timeDraft.trim() || !Number.isFinite(parsed)) {
      setTimeDraft(state.video.currentTime.toFixed(3))
      return
    }
    const clamped = Math.min(
      state.video.duration ?? Number.POSITIVE_INFINITY,
      Math.max(0, parsed),
    )
    setTimeDraft(clamped.toFixed(3))
    seek(clamped)
  }

  return (
    <section className="video-section" aria-label="Video preview">
      <div className="video-stage">
        {document?.video?.url ? (
          <video
            key={`${document.id}:${state.video.mediaGeneration}`}
            ref={videoRef}
            src={document.video.url}
            controls
            preload="metadata"
            onLoadedMetadata={(event) =>
              dispatch({
                type: 'VIDEO_PATCH',
                patch: {
                  duration:
                    document.video?.duration_s ?? event.currentTarget.duration,
                },
              })
            }
            onDurationChange={(event) =>
              dispatch({
                type: 'VIDEO_PATCH',
                patch: {
                  duration:
                    document.video?.duration_s ??
                    (Number.isFinite(event.currentTarget.duration)
                      ? event.currentTarget.duration
                      : null),
                },
              })
            }
            onTimeUpdate={(event) =>
              dispatch({
                type: 'VIDEO_PATCH',
                patch: { currentTime: event.currentTarget.currentTime },
              })
            }
            onPlay={() =>
              dispatch({ type: 'VIDEO_PATCH', patch: { paused: false } })
            }
            onPause={() =>
              dispatch({ type: 'VIDEO_PATCH', patch: { paused: true } })
            }
            onRateChange={(event) =>
              dispatch({
                type: 'VIDEO_PATCH',
                patch: { playbackRate: event.currentTarget.playbackRate },
              })
            }
            onError={() =>
              dispatch({
                type: 'VIDEO_PATCH',
                patch: {
                  previewStatus: 'unavailable',
                  previewMessage: 'This browser cannot play the video codec.',
                },
              })
            }
          />
        ) : (
          <div className="video-unavailable">
            <strong>Preview unavailable</strong>
            <span>{document?.video?.display_path ?? 'No video was resolved.'}</span>
            {document?.load_error && <span>{document.load_error.message}</span>}
          </div>
        )}
      </div>
      <div className="transport" aria-label="Review transport">
        <button
          type="button"
          className="icon-button"
          onClick={previous}
          disabled={!hasPrevious}
          title="Previous sample ([)"
          aria-label="Previous sample"
        >
          <SkipBack size={17} />
        </button>
        <button
          type="button"
          className="icon-button primary-icon"
          onClick={togglePlay}
          disabled={
            !document?.video?.url || state.video.previewStatus === 'unavailable'
          }
          title="Play or pause (Space)"
          aria-label={state.video.paused ? 'Play video' : 'Pause video'}
        >
          {state.video.paused ? <Play size={17} /> : <Pause size={17} />}
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={next}
          disabled={!hasNext}
          title="Next sample (])"
          aria-label="Next sample"
        >
          <SkipForward size={17} />
        </button>
        <span className="transport-divider" />
        <button
          type="button"
          className="icon-button"
          onClick={() => nudge(-0.1)}
          title="Back 0.1 seconds (Left)"
          aria-label="Nudge playhead back 0.1 seconds"
        >
          <StepBack size={16} />
        </button>
        <button
          type="button"
          className="icon-button"
          onClick={() => nudge(0.1)}
          title="Forward 0.1 seconds (Right)"
          aria-label="Nudge playhead forward 0.1 seconds"
        >
          <StepForward size={16} />
        </button>
        <label className="time-control">
          <span>Time</span>
          <input
            className="mono"
            ref={timeInputRef}
            type="number"
            min="0"
            max={state.video.duration ?? undefined}
            step="0.001"
            value={timeDraft}
            onChange={(event) => setTimeDraft(event.target.value)}
            onBlur={() => {
              if (skipNextTimeBlur.current) {
                skipNextTimeBlur.current = false
              } else {
                commitTimeDraft()
              }
            }}
            onKeyDown={(event) => {
              if (event.key === 'Enter') {
                event.preventDefault()
                skipNextTimeBlur.current = true
                commitTimeDraft()
                event.currentTarget.blur()
              } else if (event.key === 'Escape') {
                skipNextTimeBlur.current = true
                setTimeDraft(state.video.currentTime.toFixed(3))
                event.currentTarget.blur()
              }
            }}
          />
        </label>
        <label className="rate-control">
          <span className="sr-only">Playback rate</span>
          <select
            value={state.video.playbackRate}
            onChange={(event) => {
              const rate = Number(event.target.value)
              if (videoRef.current) videoRef.current.playbackRate = rate
              dispatch({
                type: 'VIDEO_PATCH',
                patch: { playbackRate: rate },
              })
            }}
          >
            <option value="0.5">0.5×</option>
            <option value="1">1×</option>
            <option value="1.5">1.5×</option>
            <option value="2">2×</option>
          </select>
        </label>
        <button
          type="button"
          className="button add-button"
          onClick={addPoint}
          disabled={!document?.editing_enabled || !target || hasFormErrors}
          title="Add point at playhead (A)"
        >
          <CirclePlus size={16} /> Add point <kbd>A</kbd>
        </button>
        <div className="preview-diagnostic mono" role="status">
          {state.video.seekRequest.sampleTime !== null && (
            <span>Sample {formatSeconds(state.video.seekRequest.sampleTime)}</span>
          )}
          {state.video.shownFrameTime !== null && (
            <span>Shown {formatSeconds(state.video.shownFrameTime)}</span>
          )}
          {state.video.previewStatus === 'seeking' && <span>Seeking…</span>}
        </div>
      </div>
      {state.video.previewMessage && (
        <div className="inline-warning" role="alert">
          {state.video.previewMessage}{' '}
          {document?.video?.display_path && (
            <span className="mono">{document.video.display_path}</span>
          )}{' '}
          {document?.video?.content_type && `(${document.video.content_type})`}
        </div>
      )}
    </section>
  )
}
