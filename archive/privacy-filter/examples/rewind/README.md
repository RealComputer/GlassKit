# Rewind Example App

Reference implementation showcasing privacy-filtered video streaming with React and TypeScript.

## Overview

Web application demonstrating the privacy infrastructure capabilities:

- Real-time video streaming with face anonymization
- Consent management interface
- Recording playback system
- WebRTC/WHEP streaming integration

## Prerequisites

- Node.js
- Backend services running (see [backend README](../../backend/README.md))

## Installation

```bash
# Install dependencies
npm install

# Start development server
npm run dev

# Open browser
open http://localhost:5173
```

## Features

### Live Stream Viewer
- WebRTC streaming via WHEP protocol
- Connection status monitoring
- Automatic reconnection handling
- Full-screen support

### Consent Management
- List consented individuals with face images
- View consent timestamps and names
- Revoke consent with confirmation
- Auto-refresh every 5 seconds

### Recording Playback
- Browse available recordings
- Stream playback with full controls
- Delete recordings with confirmation
- Duration and timestamp display
- Auto-refresh every 10 seconds

## Development

```bash
npm run build # Build for production
npm run lint  # Run ESLint
```
