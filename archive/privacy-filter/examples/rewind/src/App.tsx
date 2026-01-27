import { useState, useCallback } from 'react'
import WHEPClient from './components/WHEPClient'
import RecordingsList from './components/RecordingsList'
import RecordingPlayer from './components/RecordingPlayer'
import ConsentList from './components/ConsentList'
import type { Recording } from './services/recordings'
import './components/WHEPClient.css'
import './App.css'

interface VideoStats {
  resolution: {
    width: number | null;
    height: number | null;
  };
  fps: number | null;
  framesDecoded: number | null;
}

function App() {
  const [activeTab, setActiveTab] = useState<'vault' | 'ai'>('vault')
  const [connectionState, setConnectionState] = useState<RTCPeerConnectionState>('new')
  const [error, setError] = useState<string | null>(null)
  const [selectedRecording, setSelectedRecording] = useState<Recording | null>(null)
  const [showRecordingPlayer, setShowRecordingPlayer] = useState(false)
  const [videoStats, setVideoStats] = useState<VideoStats>({
    resolution: { width: null, height: null },
    fps: null,
    framesDecoded: null
  })

  // WHEP endpoint configuration (port 8889 as specified in requirements)
  const whepEndpoint = 'http://localhost:8889/filtered/whep'

  const handleConnectionStateChange = useCallback((state: RTCPeerConnectionState) => {
    setConnectionState(state)
    console.log('Connection state changed:', state)
  }, [])

  const handleError = useCallback((err: Error) => {
    setError(err.message)
    console.error('WHEP Client Error:', err)
  }, [])

  const handleStatsUpdate = useCallback((stats: VideoStats) => {
    setVideoStats(stats)
  }, [])

  const clearError = useCallback(() => {
    setError(null)
  }, [])

  const handleSelectRecording = useCallback((recording: Recording) => {
    setSelectedRecording(recording)
    if (recording) {
      setShowRecordingPlayer(true)
    }
  }, [])

  const handleClosePlayer = useCallback(() => {
    setShowRecordingPlayer(false)
  }, [])

  return (
    <div className="app">
      <header className="app-header">
        <h1>Example App: Rewind</h1>
        <p className="subtitle">
          Using the privacy filter, this showcases live privacy-preserving streams, recordings, and consent management.
        </p>
        <nav className="tab-navigation">
          <button
            className={`tab-button ${activeTab === 'vault' ? 'active' : ''}`}
            onClick={() => setActiveTab('vault')}
          >
            Vault
          </button>
          <button
            className={`tab-button ${activeTab === 'ai' ? 'active' : ''}`}
            onClick={() => setActiveTab('ai')}
          >
            AI
          </button>
        </nav>
      </header>

      <main className="main-content">
        {activeTab === 'vault' ? (
          <>
            <section className="video-section">
              <h2>Live Stream</h2>

              <WHEPClient
                whepEndpoint={whepEndpoint}
                onConnectionStateChange={handleConnectionStateChange}
                onError={handleError}
                onStatsUpdate={handleStatsUpdate}
                className="main-video-player"
              />
            </section>

            <aside className="sidebar">
              <section className="recordings-panel">
                <h3>Recordings</h3>
                <RecordingsList
                  onSelectRecording={handleSelectRecording}
                  selectedRecording={selectedRecording}
                  isStreamActive={connectionState === 'connected'}
                />
              </section>

              <section className="consent-panel">
                <h3>Consents</h3>
                <ConsentList />
              </section>

              <section className="connection-panel">
                <h3>Connection Status</h3>
                <div className="status-grid">
                  <div className="status-item">
                    <label>WebRTC State:</label>
                    <span className={`status-badge ${connectionState}`}>
                      {connectionState}
                    </span>
                  </div>
                  <div className="status-item">
                    <label>Endpoint:</label>
                    <code className="endpoint">{whepEndpoint}</code>
                  </div>
                  {connectionState === 'connected' && (
                    <>
                      <div className="status-item">
                        <label>Resolution:</label>
                        <span>{videoStats.resolution.width ?? '—'} × {videoStats.resolution.height ?? '—'}</span>
                      </div>
                      <div className="status-item">
                        <label>FPS:</label>
                        <span>{videoStats.fps?.toFixed(1) ?? '—'}</span>
                      </div>
                      <div className="status-item">
                        <label>Frames:</label>
                        <span>{videoStats.framesDecoded ?? '—'}</span>
                      </div>
                    </>
                  )}
                </div>

                {error && (
                  <div className="error-panel">
                    <h4>Error</h4>
                    <p>{error}</p>
                    <button onClick={clearError} className="clear-error-btn">
                      Clear
                    </button>
                  </div>
                )}
              </section>
            </aside>
          </>
        ) : (
          <div className="ai-tab-content">
            <section className="ai-chat-section">
              <h2>AI Chat</h2>
              <p className="ai-description">
                Interact with AI assistant for video analysis and insights.
              </p>
              <div className="coming-soon-large">
                <span>Coming Soon</span>
                <p>AI-powered video analysis and chat features will be available here.</p>
              </div>
            </section>
          </div>
        )}
      </main>

      <footer className="app-footer">
        <p>
          Privacy-first video streaming infrastructure •
          Built with React, WebRTC, and WHEP protocol
        </p>
      </footer>

      {showRecordingPlayer && (
        <div className="recording-modal-overlay" onClick={handleClosePlayer}>
          <div className="recording-modal" onClick={(e) => e.stopPropagation()}>
            <button className="modal-close-btn" onClick={handleClosePlayer}>
              ×
            </button>
            <RecordingPlayer recording={selectedRecording} />
          </div>
        </div>
      )}
    </div>
  )
}

export default App
