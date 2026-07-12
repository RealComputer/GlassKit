import { Layers3, ZoomIn } from "lucide-react";
import { useEffect, useMemo, useRef, useState, type CSSProperties, type PointerEvent } from "react";
import { createPortal } from "react-dom";
import type { ReviewSample } from "../api/types.ts";
import { useApp } from "../state/AppContext.tsx";
import { expectationColor } from "../timeline/colors.ts";
import {
  anchoredScrollLeft,
  markerSelector,
  positionToTime,
  rulerTicks,
  TIMELINE_LABEL_WIDTH,
  timelineTrackWidth,
  timeToPosition,
} from "../timeline/math.ts";
import { expectationSummary, formatSeconds } from "../utils/format.ts";

type TimelineStyle = CSSProperties & {
  "--track-width"?: string;
  "--position"?: string;
  "--expect-color"?: string;
};

interface HoveredSample {
  sample: ReviewSample;
  x: number;
  y: number;
}

const SAMPLE_HOVER_RADIUS_PX = 18;

function findNearestSample(samples: ReviewSample[], timestamp: number): ReviewSample | null {
  return samples.reduce<ReviewSample | null>((nearest, sample) => {
    if (!nearest) return sample;
    return Math.abs(sample.timestamp_s - timestamp) < Math.abs(nearest.timestamp_s - timestamp)
      ? sample
      : nearest;
  }, null);
}

function colorStyle(sample: ReviewSample): TimelineStyle {
  return { "--expect-color": expectationColor(sample) };
}

export function Timeline({ controlsHost }: { controlsHost: HTMLDivElement | null }) {
  const { state, dispatch, selectSample, selectTarget, seek } = useApp();
  const workspace = state.selectedCaseId ? state.caseFileWorkspaces[state.selectedCaseId] : null;
  const document = workspace?.document;
  const duration = state.video.duration ?? document?.video?.duration_s ?? 0;
  const scrollRef = useRef<HTMLDivElement>(null);
  const activeScrubPointerRef = useRef<number | null>(null);
  const pendingScrubTimeRef = useRef<number | null>(null);
  const lastScrubTimeRef = useRef<number | null>(null);
  const scrubFrameRef = useRef<number | null>(null);
  const [viewportWidth, setViewportWidth] = useState(800);
  const [hoveredSample, setHoveredSample] = useState<HoveredSample | null>(null);
  const trackWidth = timelineTrackWidth(viewportWidth, state.zoom);
  const targets = useMemo(() => {
    const all = document?.targets ?? [];
    return state.selectedLaneOnly
      ? all.filter((target) => target.id === state.selectedTargetId)
      : all;
  }, [document?.targets, state.selectedLaneOnly, state.selectedTargetId]);

  useEffect(() => {
    const element = scrollRef.current;
    if (!element) return;
    const update = () => setViewportWidth(element.clientWidth);
    update();
    const observer = new ResizeObserver(update);
    observer.observe(element);
    return () => observer.disconnect();
  }, []);

  useEffect(() => {
    if (!state.selectedTargetId || !state.selectedSampleId || !scrollRef.current) return;
    const marker = scrollRef.current.querySelector<HTMLElement>(
      markerSelector(state.selectedTargetId, state.selectedSampleId),
    );
    marker?.scrollIntoView({ behavior: "smooth", block: "nearest", inline: "center" });
  }, [state.selectedSampleId, state.selectedTargetId]);

  useEffect(
    () => () => {
      if (scrubFrameRef.current !== null) cancelAnimationFrame(scrubFrameRef.current);
    },
    [],
  );

  const setZoom = (zoom: 1 | 2 | 4 | 8) => {
    const element = scrollRef.current;
    if (!element || zoom === state.zoom) return;
    const anchorTime =
      document?.targets
        .find((target) => target.id === state.selectedTargetId)
        ?.samples.find((sample) => sample.id === state.selectedSampleId)?.timestamp_s ??
      state.video.currentTime;
    const anchorRatio = timeToPosition(anchorTime, duration);
    const oldWidth = trackWidth;
    const oldScroll = element.scrollLeft;
    dispatch({ type: "SET_ZOOM", value: zoom });
    requestAnimationFrame(() => {
      const newWidth = timelineTrackWidth(element.clientWidth, zoom);
      element.scrollLeft = anchoredScrollLeft(
        oldScroll,
        element.clientWidth - TIMELINE_LABEL_WIDTH,
        oldWidth,
        newWidth,
        anchorRatio,
      );
    });
  };

  const timeFromPointer = (event: PointerEvent<HTMLDivElement>) => {
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return 0;
    return positionToTime((event.clientX - rect.left) / rect.width, duration);
  };

  const requestScrub = (time: number) => {
    if (lastScrubTimeRef.current !== null && Math.abs(lastScrubTimeRef.current - time) < 1e-6)
      return;
    lastScrubTimeRef.current = time;
    seek(time);
  };

  const cancelScheduledScrub = () => {
    if (scrubFrameRef.current !== null) cancelAnimationFrame(scrubFrameRef.current);
    scrubFrameRef.current = null;
    pendingScrubTimeRef.current = null;
  };

  const startScrub = (event: PointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 || (event.target as Element).closest("button")) return;
    event.preventDefault();
    event.currentTarget.setPointerCapture?.(event.pointerId);
    activeScrubPointerRef.current = event.pointerId;
    lastScrubTimeRef.current = null;
    requestScrub(timeFromPointer(event));
  };

  const continueScrub = (event: PointerEvent<HTMLDivElement>) => {
    if (activeScrubPointerRef.current !== event.pointerId) return;
    pendingScrubTimeRef.current = timeFromPointer(event);
    if (scrubFrameRef.current !== null) return;
    scrubFrameRef.current = requestAnimationFrame(() => {
      scrubFrameRef.current = null;
      const time = pendingScrubTimeRef.current;
      pendingScrubTimeRef.current = null;
      if (time !== null) requestScrub(time);
    });
  };

  const finishScrub = (event: PointerEvent<HTMLDivElement>) => {
    if (activeScrubPointerRef.current !== event.pointerId) return;
    cancelScheduledScrub();
    requestScrub(timeFromPointer(event));
    activeScrubPointerRef.current = null;
    if (event.currentTarget.hasPointerCapture?.(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const cancelScrub = (event: PointerEvent<HTMLDivElement>) => {
    if (activeScrubPointerRef.current !== event.pointerId) return;
    cancelScheduledScrub();
    activeScrubPointerRef.current = null;
  };

  const scrubHandlers = {
    onPointerDown: startScrub,
    onPointerMove: continueScrub,
    onPointerUp: finishScrub,
    onPointerCancel: cancelScrub,
    onLostPointerCapture: cancelScrub,
  };

  const updateHoveredSample = (event: PointerEvent<HTMLDivElement>, samples: ReviewSample[]) => {
    if (activeScrubPointerRef.current !== null) {
      setHoveredSample(null);
      return;
    }
    const rect = event.currentTarget.getBoundingClientRect();
    if (rect.width <= 0) return;
    const pointerX = Math.min(rect.width, Math.max(0, event.clientX - rect.left));
    const timestamp = positionToTime(pointerX / rect.width, duration);
    const sample = findNearestSample(samples, timestamp);
    if (!sample) return;
    const sampleX = timeToPosition(sample.timestamp_s, duration) * rect.width;
    if (Math.abs(sampleX - pointerX) > SAMPLE_HOVER_RADIUS_PX) {
      setHoveredSample(null);
      return;
    }
    setHoveredSample({
      sample,
      x: Math.min(window.innerWidth - 60, Math.max(60, event.clientX)),
      y: event.clientY,
    });
  };

  const ticks = rulerTicks(duration, state.zoom);
  const rootStyle: TimelineStyle = { "--track-width": `${trackWidth}px` };
  const playheadStyle: TimelineStyle = {
    left: `${
      TIMELINE_LABEL_WIDTH + timeToPosition(state.video.currentTime, duration) * trackWidth
    }px`,
  };

  const controls = (
    <div className="timeline-toolbar">
      <ZoomIn size={15} aria-hidden="true" />
      <div className="segmented" aria-label="Timeline zoom">
        {([1, 2, 4, 8] as const).map((zoom) => (
          <button
            key={zoom}
            type="button"
            className={state.zoom === zoom ? "selected" : ""}
            onClick={() => setZoom(zoom)}
            aria-pressed={state.zoom === zoom}
          >
            {zoom === 1 ? "Fit" : `${zoom}×`}
          </button>
        ))}
      </div>
      <label className="toggle-control" htmlFor="selected-lane-only">
        <input
          id="selected-lane-only"
          type="checkbox"
          checked={state.selectedLaneOnly}
          onChange={(event) =>
            dispatch({
              type: "SET_SELECTED_LANE_ONLY",
              value: event.target.checked,
            })
          }
        />
        <Layers3 size={15} /> Selected only
      </label>
    </div>
  );

  return (
    <section className="timeline-section" aria-label="Sample timeline">
      {controlsHost && createPortal(controls, controlsHost)}
      <div
        className={`timeline-scroll${state.zoom === 1 ? " fit" : ""}`}
        ref={scrollRef}
        style={rootStyle}
        onScroll={() => setHoveredSample(null)}
      >
        <div className="timeline-content">
          <div className="time-ruler">
            <div className="lane-label ruler-label">Target / time</div>
            <div
              className="ruler-track"
              role="slider"
              tabIndex={0}
              aria-label="Video playhead"
              aria-valuemin={0}
              aria-valuemax={duration}
              aria-valuenow={state.video.currentTime}
              aria-valuetext={formatSeconds(state.video.currentTime)}
              title="Click or drag to seek"
              {...scrubHandlers}
            >
              {ticks.map((tick, index) => {
                const isEnd = index > 0 && index === ticks.length - 1;
                return (
                  <span
                    key={tick}
                    className={`ruler-tick mono${isEnd ? " end" : ""}`}
                    style={
                      isEnd ? { right: 0 } : { left: `${timeToPosition(tick, duration) * 100}%` }
                    }
                  >
                    {formatSeconds(tick)}
                  </span>
                );
              })}
            </div>
          </div>
          <div className="playhead" style={playheadStyle} aria-hidden="true" />
          <div className="timeline-lanes">
            {targets.map((target) => {
              const focused = target.id === state.selectedTargetId;
              return (
                <div key={target.id} className={`timeline-lane ${focused ? "focused" : "context"}`}>
                  <button
                    type="button"
                    className="lane-label"
                    title={target.label ?? target.id}
                    onClick={() => void selectTarget(target.id)}
                  >
                    <span>{target.label ?? target.id}</span>
                    <small>{target.samples.length}</small>
                  </button>
                  <div
                    className="lane-track"
                    {...scrubHandlers}
                    onPointerMove={(event) => {
                      continueScrub(event);
                      updateHoveredSample(event, target.samples);
                    }}
                    onPointerLeave={() => setHoveredSample(null)}
                  >
                    {target.samples.map((sample) => {
                      const markerStyle: TimelineStyle = {
                        "--position": `${timeToPosition(sample.timestamp_s, duration) * 100}%`,
                        ...colorStyle(sample),
                      };
                      const selected =
                        target.id === state.selectedTargetId &&
                        sample.id === state.selectedSampleId;
                      return (
                        <button
                          key={sample.id}
                          type="button"
                          className={`sample-marker ${selected ? "selected" : ""}`}
                          style={markerStyle}
                          data-sample-id={sample.id}
                          data-target-id={target.id}
                          onClick={() => void selectSample(target.id, sample.id)}
                          onPointerUp={(event) => event.currentTarget.blur()}
                          aria-pressed={selected}
                          aria-label={`${target.label ?? target.id}, ${formatSeconds(
                            sample.timestamp_s,
                          )}, expected ${expectationSummary(sample)}`}
                        />
                      );
                    })}
                  </div>
                </div>
              );
            })}
            {targets.length === 0 && <div className="empty-lanes">No target lanes to show.</div>}
          </div>
        </div>
      </div>
      {hoveredSample && (
        <div
          className="timeline-tooltip mono"
          role="tooltip"
          style={{ left: hoveredSample.x, top: hoveredSample.y }}
        >
          {formatSeconds(hoveredSample.sample.timestamp_s)} ·{" "}
          {expectationSummary(hoveredSample.sample)}
        </div>
      )}
    </section>
  );
}
