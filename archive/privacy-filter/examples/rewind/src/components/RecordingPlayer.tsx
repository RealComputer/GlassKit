import { useEffect, useRef } from 'react'
import type { Recording } from '../services/recordings'
import { recordingsService } from '../services/recordings'
import './RecordingPlayer.css'

interface RecordingPlayerProps {
  recording: Recording | null
}

function RecordingPlayer({ recording }: RecordingPlayerProps) {
  const videoRef = useRef<HTMLVideoElement>(null)

  useEffect(() => {
    if (videoRef.current && recording) {
      videoRef.current.load()
      // Set default volume to 30%
      videoRef.current.volume = 0.3
    }
  }, [recording])

  if (!recording) {
    return (
      <div className="recording-player">
        <div className="no-recording">
          <p>Select a recording to play</p>
        </div>
      </div>
    )
  }

  return (
    <div className="recording-player">
      <div className="player-header">
        <h4>Playing Recording</h4>
        <div className="recording-details">
          <span className="recording-timestamp">
            {recordingsService.formatTimestamp(recording.start)}
          </span>
          <span className="recording-duration">
            {recordingsService.formatDuration(recording.duration)}
          </span>
        </div>
      </div>
      <div className="video-container">
        <video
          ref={videoRef}
          controls
          autoPlay
          className="recording-video"
          key={recording.url}
        >
          <source src={recording.url} type="video/mp4" />
          Your browser does not support the video tag.
        </video>
      </div>
    </div>
  )
}

export default RecordingPlayer