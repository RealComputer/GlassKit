export interface PreviewState {
  status: 'seeking' | 'ready' | 'unavailable'
  shownFrameTime: number | null
  message: string | null
}

type PreviewListener = (state: PreviewState) => void

const SEEK_TOLERANCE_S = 0.05
const FRAME_CALLBACK_TIMEOUT_MS = 500
const OVERALL_TIMEOUT_MS = 5_000

export class PreciseVideoSeeker {
  private generation = 0
  private cleanupCurrent: (() => void) | null = null
  private readonly video: HTMLVideoElement
  private readonly onState: PreviewListener

  constructor(video: HTMLVideoElement, onState: PreviewListener) {
    this.video = video
    this.onState = onState
  }

  seek(requestedTime: number): number {
    const generation = ++this.generation
    this.cleanupCurrent?.()
    let finished = false
    let presentationPending = false
    let frameCallbackId: number | null = null
    const cleanups: (() => void)[] = []
    const cleanup = () => {
      for (const item of cleanups.splice(0)) item()
      if (
        frameCallbackId !== null &&
        'cancelVideoFrameCallback' in this.video
      ) {
        this.video.cancelVideoFrameCallback(frameCallbackId)
      }
      frameCallbackId = null
    }
    this.cleanupCurrent = cleanup

    const finish = (state: PreviewState) => {
      if (finished || generation !== this.generation) return
      finished = true
      cleanup()
      this.onState(state)
    }

    const listen = (name: string, listener: EventListener) => {
      this.video.addEventListener(name, listener)
      cleanups.push(() => this.video.removeEventListener(name, listener))
    }

    const overallTimer = window.setTimeout(() => {
      finish({
        status: 'unavailable',
        shownFrameTime: null,
        message: 'Preview did not become ready after seeking.',
      })
    }, OVERALL_TIMEOUT_MS)
    cleanups.push(() => window.clearTimeout(overallTimer))

    const fail = () => {
      finish({
        status: 'unavailable',
        shownFrameTime: null,
        message: 'The browser could not present this video preview.',
      })
    }
    listen('error', fail)
    listen('emptied', fail)

    this.onState({ status: 'seeking', shownFrameTime: null, message: null })
    if (this.video.error) {
      fail()
      return generation
    }

    const completePresentation = () => {
      if (
        generation !== this.generation ||
        finished ||
        presentationPending
      ) return
      presentationPending = true
      if ('requestVideoFrameCallback' in this.video) {
        const fallbackTimer = window.setTimeout(() => {
          finish({ status: 'ready', shownFrameTime: null, message: null })
        }, FRAME_CALLBACK_TIMEOUT_MS)
        cleanups.push(() => window.clearTimeout(fallbackTimer))
        frameCallbackId = this.video.requestVideoFrameCallback(
          (_now, metadata) => {
            finish({
              status: 'ready',
              shownFrameTime: metadata.mediaTime,
              message: null,
            })
          },
        )
      } else {
        finish({ status: 'ready', shownFrameTime: null, message: null })
      }
    }

    const assign = () => {
      if (generation !== this.generation || finished) return
      const duration = Number.isFinite(this.video.duration)
        ? Math.max(0, this.video.duration)
        : requestedTime
      const target = Math.min(Math.max(0, requestedTime), duration)
      const qualifies = () =>
        !this.video.seeking &&
        Math.abs(this.video.currentTime - target) <= SEEK_TOLERANCE_S
      const onSeeked = () => {
        if (generation === this.generation && qualifies()) {
          completePresentation()
        }
      }
      listen('seeked', onSeeked)
      try {
        this.video.currentTime = target
      } catch {
        fail()
        return
      }
      // Browsers do not consistently emit `seeked` when assigning the current
      // position. Check in a microtask after the assignment before waiting.
      queueMicrotask(() => {
        if (generation === this.generation && qualifies()) {
          completePresentation()
        }
      })
    }

    if (this.video.readyState === HTMLMediaElement.HAVE_NOTHING) {
      listen('loadedmetadata', assign)
    } else {
      assign()
    }
    return generation
  }

  cancel(): void {
    this.generation += 1
    this.cleanupCurrent?.()
    this.cleanupCurrent = null
  }
}
