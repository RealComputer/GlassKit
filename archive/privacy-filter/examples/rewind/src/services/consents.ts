const API_BASE_URL = 'http://localhost:8000'

export interface ConsentInfo {
  name: string
  time: number  // Unix timestamp
  id: string    // Filename without .jpg extension
}

export class ConsentsService {
  static async listConsents(): Promise<ConsentInfo[]> {
    try {
      const response = await fetch(`${API_BASE_URL}/consents`)
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
      return await response.json()
    } catch (error) {
      console.error('Error fetching consents:', error)
      throw error
    }
  }

  static getImageUrl(consentId: string): string {
    return `${API_BASE_URL}/consents/${consentId}/image`
  }

  static async revokeConsent(consentId: string): Promise<void> {
    try {
      const response = await fetch(`${API_BASE_URL}/consents/${consentId}`, {
        method: 'DELETE',
      })
      if (!response.ok) {
        throw new Error(`HTTP error! status: ${response.status}`)
      }
    } catch (error) {
      console.error('Error revoking consent:', error)
      throw error
    }
  }
}