export interface Recording {
  start: string
  duration: number
  url: string
}

export class RecordingsService {
  private readonly mediaMtxBaseUrl: string
  private readonly mediaMtxApiUrl: string
  private readonly path: string

  constructor(
    mediaMtxBaseUrl = 'http://localhost:9996',
    mediaMtxApiUrl = 'http://localhost:9997',
    path = 'filtered'
  ) {
    this.mediaMtxBaseUrl = mediaMtxBaseUrl
    this.mediaMtxApiUrl = mediaMtxApiUrl
    this.path = path
  }

  async fetchRecordings(): Promise<Recording[]> {
    try {
      const response = await fetch(`${this.mediaMtxBaseUrl}/list?path=${this.path}`)
      if (!response.ok) {
        throw new Error(`Failed to fetch recordings: ${response.statusText}`)
      }
      const data = await response.json()
      return data || []
    } catch (error) {
      console.error('Error fetching recordings:', error)
      throw error
    }
  }

  async deleteRecording(start: string): Promise<void> {
    try {
      const response = await fetch(
        `${this.mediaMtxApiUrl}/v3/recordings/deletesegment?path=${this.path}&start=${encodeURIComponent(start)}`,
        {
          method: 'DELETE',
          headers: {
            'Content-Type': 'application/json',
          },
        }
      )
      if (!response.ok) {
        throw new Error(`Failed to delete recording: ${response.statusText}`)
      }
    } catch (error) {
      console.error('Error deleting recording:', error)
      throw error
    }
  }

  formatDuration(seconds: number): string {
    const hours = Math.floor(seconds / 3600)
    const minutes = Math.floor((seconds % 3600) / 60)
    const secs = Math.floor(seconds % 60)
    
    if (hours > 0) {
      return `${hours}:${minutes.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`
    }
    return `${minutes}:${secs.toString().padStart(2, '0')}`
  }

  formatTimestamp(timestamp: string): string {
    try {
      const date = new Date(timestamp)
      return date.toLocaleString()
    } catch {
      return timestamp
    }
  }
}

export const recordingsService = new RecordingsService()