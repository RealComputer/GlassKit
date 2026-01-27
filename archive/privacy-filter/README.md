# Privacy Infrastructure for Smart Glasses

Build smart glasses apps without privacy concerns.

<img width="1600" height="956" src="https://github.com/user-attachments/assets/2f71bd47-c959-4e6f-8d4e-28e4ca23d334" />

Smart glasses apps face privacy hurdles. This real-time privacy filter sits between the camera and the app, automatically ensuring compliance.

**How it works:** Replace your raw camera feed with our filtered stream. The filter processes live video, applies privacy protections, and outputs a compliant stream in real time. Use this processed stream for AI apps, social apps, or anything else.

**Features:**

- **Anonymizes faces** of non-consenting individuals (configurable: blur or solid ellipse masking)
- **Manages consent** (e.g., detects verbal consent such as "I consent to be captured" and remembers it)
- **Real-time processing** – 720p 30fps on laptop
- **100% offline** – no cloud dependencies
- **Recording**

**Developer-friendly:**

- Easy camera replacement
- RTMP input / multiple output formats
- HTTP API for control

## Demo

https://github.com/user-attachments/assets/42f0eee9-6366-4078-abc0-0226a8b8b1aa

Using a smartphone as the camera. Smart glasses demos [here](https://x.com/caydengineer/status/1945236074961236481) and [here](https://x.com/s_diana_k/status/1944500312116723973).

## Tech Stack

Runs offline on a laptop. Built with FFmpeg (stream decode/encode), OpenCV (face detection/anonymization), Faster Whisper (voice transcription), and Phi-3.5 Mini (LLM for consent detection).

## Quick Start

See the [backend README](./backend/README.md), [example app README](./examples/rewind/README.md), and [CLAUDE.md](./CLAUDE.md) for technical details.

## Use Cases

Works with any camera-based app, for example:

- **AI Assistants** – Memory augmentation without privacy risks
- **Social Apps** – Live streaming with automatic protection
- **Enterprise** – Compliant workplace recording
- **Content Creation** – Automatic face anonymization for vlogs

## Roadmap

This project is under active development.

- Integration guides for various smart glasses
- Additional privacy filters (text, objects)
- Speech anonymization
- Location-based auto shutoff
- Legal compliance templates
- VLM integration
- Active speaker detection
- More input protocols (currently RTMP)
- Deployment guide
- etc.

## Contributing

Feedback, questions, and contributions are welcome.
