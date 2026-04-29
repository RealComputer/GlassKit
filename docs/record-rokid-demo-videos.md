# Recording Rokid Glasses Demo Videos

If your glasses app is not using the camera, you can try the AR recording feature in the Hi Rokid app. If your app is using the camera, use Android screen capture for the display and record the real-world point of view separately.

## Why Hi Rokid Recording May Not Work

The AR recording feature in the Hi Rokid app needs camera access. Vision-enabled apps also need camera access, so the two recording flows can compete for the same camera.

## Workflow I Use

For some demo videos in this repo, I record two sources:

1. The glasses display with `scrcpy`, for example: `scrcpy --no-audio --record ui.mp4`
    - An `adb` connection is required, either over a cable or wirelessly.
2. The real-world point of view with a separate head-mounted camera

Then I combine the two videos with `ffmpeg` or a video editor.

A clap, tap, or obvious UI action at the beginning makes the videos easier to sync during editing.

## Combining The Videos

TODO

## What About A Single In-App Recording?

The cleanest long-term solution is to implement recording inside the glasses app:

1. Capture the screen or app UI with Android screen-capture APIs
2. Use the app's own camera feed for both app logic and recording
3. Compose the UI and camera feed into one video inside the app

That avoids asking the Hi Rokid app and your own app to use the camera at the same time.

This is on our roadmap.
