import {
  CirclePlus,
  Download,
  Pause,
  Play,
  SkipBack,
  SkipForward,
  StepBack,
  StepForward,
} from "lucide-react";
import { useEffect, useMemo, useRef, useState } from "react";
import { useApp } from "../state/AppContext.tsx";
import { findSampleAt } from "../state/editing.ts";
import { PreciseVideoSeeker } from "../video/PreciseVideoSeeker.ts";
import {
  downloadVideoFrame,
  frameDownloadFilename,
  isVideoFrameReady,
} from "../video/downloadFrame.ts";

const SEEKING_MESSAGE_DELAY_MS = 200;

export function DelayedSeekingStatus() {
  const [visible, setVisible] = useState(false);

  useEffect(() => {
    const timer = window.setTimeout(() => setVisible(true), SEEKING_MESSAGE_DELAY_MS);
    return () => window.clearTimeout(timer);
  }, []);

  return visible ? <span>Seeking…</span> : null;
}

export function VideoPanel() {
  const { state, dispatch, selectSample, addSample, seek } = useApp();
  const videoRef = useRef<HTMLVideoElement>(null);
  const timeInputRef = useRef<HTMLInputElement>(null);
  const seekerRef = useRef<PreciseVideoSeeker | null>(null);
  const skipNextTimeBlur = useRef(false);
  const [timeDraft, setTimeDraft] = useState("0.000");
  const [frameCaptureReady, setFrameCaptureReady] = useState(false);
  const [frameDownloadPending, setFrameDownloadPending] = useState(false);
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const document = workspace?.document;
  const target = document?.targets.find((item) => item.id === state.selectedTargetId);
  const hasFormErrors = Boolean(workspace && Object.keys(workspace.formErrors).length > 0);
  const samples = useMemo(
    () => [...(target?.samples ?? [])].sort((a, b) => a.timestamp_s - b.timestamp_s),
    [target?.samples],
  );
  const hasSampleAtVideoTime = Boolean(target && findSampleAt(target, state.video.currentTime));

  useEffect(() => {
    if (globalThis.document.activeElement !== timeInputRef.current) {
      setTimeDraft(state.video.currentTime.toFixed(3));
    }
  }, [state.video.currentTime]);

  useEffect(() => {
    setFrameCaptureReady(false);
  }, [document?.video?.url, state.video.mediaGeneration]);

  useEffect(() => {
    const video = videoRef.current;
    if (!video) return;
    const seeker = new PreciseVideoSeeker(video, (preview) => {
      dispatch({
        type: "VIDEO_PATCH",
        patch: {
          previewStatus: preview.status,
          shownFrameTime: preview.shownFrameTime,
          previewMessage: preview.message,
        },
      });
    });
    seekerRef.current = seeker;
    return () => {
      seeker.cancel();
      seekerRef.current = null;
    };
  }, [dispatch, document?.video?.url, state.video.mediaGeneration]);

  useEffect(() => {
    if (state.video.seekRequest.generation === 0) return;
    const video = videoRef.current;
    if (!document?.video?.url || !video || !seekerRef.current) {
      dispatch({
        type: "VIDEO_PATCH",
        patch: {
          previewStatus: "unavailable",
          shownFrameTime: null,
          previewMessage: "No browser-playable video is available for this case file.",
        },
      });
      return;
    }
    video.pause();
    seekerRef.current.seek(state.video.seekRequest.time);
  }, [
    dispatch,
    document?.video?.url,
    state.video.mediaGeneration,
    state.video.seekRequest.generation,
    state.video.seekRequest.time,
  ]);

  const relativeIndex = () => {
    if (state.selectedSampleId) {
      const index = samples.findIndex((sample) => sample.id === state.selectedSampleId);
      if (index >= 0) return index;
    }
    return samples.findIndex((sample) => sample.timestamp_s >= state.video.currentTime);
  };

  const previous = () => {
    const selectedIndex = state.selectedSampleId
      ? samples.findIndex((sample) => sample.id === state.selectedSampleId)
      : -1;
    const sample =
      selectedIndex >= 0
        ? samples[selectedIndex - 1]
        : [...samples].reverse().find((item) => item.timestamp_s < state.video.currentTime - 1e-9);
    if (sample && target) void selectSample(target.id, sample.id);
  };
  const next = () => {
    const index = relativeIndex();
    const sample = state.selectedSampleId
      ? samples[index + 1]
      : samples.find((item) => item.timestamp_s > state.video.currentTime + 1e-9);
    if (sample && target) void selectSample(target.id, sample.id);
  };
  const hasPrevious = state.selectedSampleId
    ? samples.findIndex((sample) => sample.id === state.selectedSampleId) > 0
    : samples.some((sample) => sample.timestamp_s < state.video.currentTime - 1e-9);
  const selectedIndex = state.selectedSampleId
    ? samples.findIndex((sample) => sample.id === state.selectedSampleId)
    : -1;
  const hasNext = state.selectedSampleId
    ? selectedIndex >= 0 && selectedIndex < samples.length - 1
    : samples.some((sample) => sample.timestamp_s > state.video.currentTime + 1e-9);

  const togglePlay = () => {
    const video = videoRef.current;
    if (!video) return;
    if (video.paused) {
      void video.play().catch(() =>
        dispatch({
          type: "VIDEO_PATCH",
          patch: {
            previewStatus: "unavailable",
            previewMessage: "This browser cannot play the video codec.",
          },
        }),
      );
    } else video.pause();
  };
  const nudge = (delta: number) =>
    seek(
      Math.min(
        state.video.duration ?? Number.POSITIVE_INFINITY,
        Math.max(0, state.video.currentTime + delta),
      ),
    );
  const commitTimeDraft = () => {
    const parsed = Number(timeDraft);
    if (!timeDraft.trim() || !Number.isFinite(parsed)) {
      setTimeDraft(state.video.currentTime.toFixed(3));
      return;
    }
    const clamped = Math.min(state.video.duration ?? Number.POSITIVE_INFINITY, Math.max(0, parsed));
    setTimeDraft(clamped.toFixed(3));
    seek(clamped);
  };
  const downloadCurrentFrame = async () => {
    const video = videoRef.current;
    if (!video || !document) return;
    setFrameDownloadPending(true);
    try {
      await downloadVideoFrame(video, frameDownloadFilename(document.name, video.currentTime));
    } catch (error) {
      dispatch({
        type: "SET_TOAST",
        value:
          error instanceof Error ? error.message : "The current frame could not be downloaded.",
      });
    } finally {
      setFrameDownloadPending(false);
    }
  };
  const updateFrameCaptureReady = (video: HTMLVideoElement) => {
    setFrameCaptureReady(isVideoFrameReady(video));
  };

  return (
    <section className="video-section" aria-label="Video preview">
      <div className="video-stage">
        {document?.video?.url ? (
          <video
            key={`${document.id}:${state.video.mediaGeneration}`}
            ref={videoRef}
            src={document.video.url}
            preload="metadata"
            muted
            onClick={togglePlay}
            onLoadedMetadata={(event) => {
              updateFrameCaptureReady(event.currentTarget);
              dispatch({
                type: "VIDEO_PATCH",
                patch: {
                  duration: document.video?.duration_s ?? event.currentTarget.duration,
                },
              });
            }}
            onLoadedData={(event) => updateFrameCaptureReady(event.currentTarget)}
            onCanPlay={(event) => updateFrameCaptureReady(event.currentTarget)}
            onDurationChange={(event) =>
              dispatch({
                type: "VIDEO_PATCH",
                patch: {
                  duration:
                    document.video?.duration_s ??
                    (Number.isFinite(event.currentTarget.duration)
                      ? event.currentTarget.duration
                      : null),
                },
              })
            }
            onTimeUpdate={(event) => {
              updateFrameCaptureReady(event.currentTarget);
              dispatch({
                type: "VIDEO_PATCH",
                patch: { currentTime: event.currentTarget.currentTime },
              });
            }}
            onSeeking={() => setFrameCaptureReady(false)}
            onSeeked={(event) => updateFrameCaptureReady(event.currentTarget)}
            onPlay={() => dispatch({ type: "VIDEO_PATCH", patch: { paused: false } })}
            onPlaying={(event) => updateFrameCaptureReady(event.currentTarget)}
            onPause={() => dispatch({ type: "VIDEO_PATCH", patch: { paused: true } })}
            onRateChange={(event) =>
              dispatch({
                type: "VIDEO_PATCH",
                patch: { playbackRate: event.currentTarget.playbackRate },
              })
            }
            onEmptied={() => setFrameCaptureReady(false)}
            onError={() => {
              setFrameCaptureReady(false);
              dispatch({
                type: "VIDEO_PATCH",
                patch: {
                  previewStatus: "unavailable",
                  previewMessage: "This browser cannot play the video codec.",
                },
              });
            }}
          />
        ) : (
          <div className="video-unavailable">
            <strong>Preview unavailable</strong>
            <span>{document?.video?.display_path ?? "No video was resolved."}</span>
            {document?.load_error && <span>{document.load_error.message}</span>}
          </div>
        )}
      </div>
      <div className="transport" aria-label="Review transport">
        <div className="transport-group" role="group" aria-label="Sample navigation">
          <button
            type="button"
            className="button transport-action"
            onClick={previous}
            disabled={!hasPrevious}
            title="Previous sample ([)"
            aria-label="Previous sample"
          >
            <SkipBack size={16} />
            <span className="transport-action-label">Previous sample</span>
            <kbd aria-hidden="true">[</kbd>
          </button>
          <button
            type="button"
            className="button transport-action"
            onClick={next}
            disabled={!hasNext}
            title="Next sample (])"
            aria-label="Next sample"
          >
            <SkipForward size={16} />
            <span className="transport-action-label">Next sample</span>
            <kbd aria-hidden="true">]</kbd>
          </button>
        </div>
        <div className="transport-stage">
          <div className="transport-group" role="group" aria-label="Video controls">
            <button
              type="button"
              className="button transport-action"
              onClick={() => nudge(-0.1)}
              title="Back 0.1 seconds (Left Arrow)"
              aria-label="Move video time back 0.1 seconds"
            >
              <StepBack size={16} className="transport-compact-icon" />
              <span className="transport-action-label">−0.1 s</span>
              <kbd aria-hidden="true">←</kbd>
            </button>
            <button
              type="button"
              className="icon-button primary-icon"
              onClick={togglePlay}
              disabled={!document?.video?.url || state.video.previewStatus === "unavailable"}
              title="Play or pause (Space)"
              aria-label={state.video.paused ? "Play video" : "Pause video"}
            >
              {state.video.paused ? <Play size={17} /> : <Pause size={17} />}
            </button>
            <button
              type="button"
              className="button transport-action"
              onClick={() => nudge(0.1)}
              title="Forward 0.1 seconds (Right Arrow)"
              aria-label="Move video time forward 0.1 seconds"
            >
              <StepForward size={16} className="transport-compact-icon" />
              <span className="transport-action-label">+0.1 s</span>
              <kbd aria-hidden="true">→</kbd>
            </button>
            <label className="time-control" htmlFor="video-time">
              <span>Time</span>
              <input
                id="video-time"
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
                    skipNextTimeBlur.current = false;
                  } else {
                    commitTimeDraft();
                  }
                }}
                onKeyDown={(event) => {
                  if (event.key === "Enter") {
                    event.preventDefault();
                    skipNextTimeBlur.current = true;
                    commitTimeDraft();
                    event.currentTarget.blur();
                  } else if (event.key === "Escape") {
                    skipNextTimeBlur.current = true;
                    setTimeDraft(state.video.currentTime.toFixed(3));
                    event.currentTarget.blur();
                  }
                }}
              />
            </label>
            <label className="rate-control" htmlFor="playback-rate">
              <span className="sr-only">Playback rate</span>
              <select
                id="playback-rate"
                value={state.video.playbackRate}
                onChange={(event) => {
                  const rate = Number(event.target.value);
                  if (videoRef.current) videoRef.current.playbackRate = rate;
                  dispatch({
                    type: "VIDEO_PATCH",
                    patch: { playbackRate: rate },
                  });
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
              className="icon-button"
              onClick={() => void downloadCurrentFrame()}
              disabled={
                !document?.video?.url ||
                !frameCaptureReady ||
                state.video.previewStatus === "seeking" ||
                state.video.previewStatus === "unavailable" ||
                frameDownloadPending
              }
              title="Download current frame"
              aria-label="Download current frame"
            >
              <Download size={16} />
            </button>
          </div>
          <div
            className="transport-group transport-create-group"
            role="group"
            aria-label="Sample creation"
          >
            <button
              type="button"
              className="button add-button"
              onClick={addSample}
              disabled={
                !document?.editing_enabled || !target || hasFormErrors || hasSampleAtVideoTime
              }
              title={
                hasSampleAtVideoTime
                  ? "A sample already exists at this time"
                  : "Add sample at video time (A)"
              }
            >
              <CirclePlus size={16} /> Add sample <kbd>A</kbd>
            </button>
          </div>
        </div>
        {state.video.previewStatus === "seeking" && (
          <div className="preview-diagnostic mono" role="status">
            <DelayedSeekingStatus key={state.video.seekRequest.generation} />
          </div>
        )}
      </div>
      {state.video.previewMessage && (
        <div className="inline-warning" role="alert">
          {state.video.previewMessage}{" "}
          {document?.video?.display_path && (
            <span className="mono">{document.video.display_path}</span>
          )}{" "}
          {document?.video?.content_type && `(${document.video.content_type})`}
        </div>
      )}
    </section>
  );
}
