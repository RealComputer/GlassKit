import { useState, useEffect } from 'react'
import { recordingsService } from '../services/recordings'
import type { Recording } from '../services/recordings'
import './RecordingsList.css'

interface RecordingsListProps {
  onSelectRecording: (recording: Recording) => void
  selectedRecording: Recording | null
  isStreamActive: boolean
}

function RecordingsList({ onSelectRecording, selectedRecording, isStreamActive }: RecordingsListProps) {
  const [recordings, setRecordings] = useState<Recording[]>([])
  const [loading, setLoading] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [deletingId, setDeletingId] = useState<string | null>(null)

  const fetchRecordings = async () => {
    setLoading(true)
    setError(null)
    try {
      const data = await recordingsService.fetchRecordings()
      setRecordings(data)
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to fetch recordings')
    } finally {
      setLoading(false)
    }
  }

  useEffect(() => {
    fetchRecordings()
    const interval = setInterval(fetchRecordings, 10000)
    return () => clearInterval(interval)
  }, [])

  const handleDelete = async (recording: Recording, e: React.MouseEvent) => {
    e.stopPropagation()
    if (!confirm('Are you sure you want to delete this recording?')) {
      return
    }

    setDeletingId(recording.start)
    try {
      await recordingsService.deleteRecording(recording.start)
      setRecordings(prev => prev.filter(r => r.start !== recording.start))
      if (selectedRecording?.start === recording.start) {
        onSelectRecording(recordings[0] || null)
      }
    } catch (err) {
      setError(err instanceof Error ? err.message : 'Failed to delete recording')
    } finally {
      setDeletingId(null)
    }
  }


  // Filter out the last recording if stream is active (it's the current streaming session)
  const displayRecordings = isStreamActive && recordings.length > 0 
    ? recordings.slice(0, -1) 
    : recordings

  if (loading && recordings.length === 0) {
    return (
      <div className="recordings-list">
        <div className="loading">Loading recordings...</div>
      </div>
    )
  }

  if (error) {
    return (
      <div className="recordings-list">
        <div className="error">
          <p>Error: {error}</p>
        </div>
      </div>
    )
  }

  if (displayRecordings.length === 0) {
    return (
      <div className="recordings-list">
        <div className="empty-state">
          <p>{isStreamActive && recordings.length === 1 ? 'No completed recordings (current stream in progress)' : 'No recordings available'}</p>
        </div>
      </div>
    )
  }

  return (
    <div className="recordings-list">
      <div className="recordings-items">
        {displayRecordings.map((recording) => (
          <div
            key={recording.start}
            className={`recording-item ${selectedRecording?.start === recording.start ? 'selected' : ''}`}
            onClick={() => onSelectRecording(recording)}
          >
            <div className="recording-info">
              <div style={{ display: 'flex', alignItems: 'center' }}>
                <span className="recording-time">
                  {recordingsService.formatTimestamp(recording.start)}
                </span>
                <span className="recording-duration">
                  {recordingsService.formatDuration(recording.duration)}
                </span>
              </div>
            </div>
            <button
              className="recording-delete-btn"
              onClick={(e) => handleDelete(recording, e)}
              disabled={deletingId === recording.start}
              title="Delete recording"
            >
              {deletingId === recording.start ? (
                <span style={{ fontSize: '0.75rem' }}>...</span>
              ) : (
                <svg width="14" height="14" viewBox="0 0 14 14" fill="none" xmlns="http://www.w3.org/2000/svg">
                  <path d="M10.5 3.5L3.5 10.5M3.5 3.5L10.5 10.5" stroke="currentColor" strokeWidth="1.5" strokeLinecap="round" strokeLinejoin="round"/>
                </svg>
              )}
            </button>
          </div>
        ))}
      </div>
    </div>
  )
}

export default RecordingsList