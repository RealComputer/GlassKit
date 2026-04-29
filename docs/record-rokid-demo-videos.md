# Recording Rokid Glasses Demo Videos

Short answer: if your glasses app is not using the camera, you can try the AR recording feature in the Hi Rokid app. If your app is using the camera, use Android screen capture for the display and record the real-world point of view separately.

## Why Hi Rokid Recording May Not Work

The AR recording feature in the Hi Rokid app needs camera access. Vision-enabled GlassKit examples also need camera access, so the two recording flows can compete for the same camera.

That is why Hi Rokid recording usually works for HUD-only demos, but can fail or become awkward when your app is actively reading camera frames for AI, object detection, or other computer-vision logic.

## Workflow I Use

For most demo videos in this repo, I capture two sources:

1. The glasses display with `scrcpy`
2. The real-world point of view with a separate head-mounted camera

Then I combine the two videos later during editing.

This gives you a clean recording of the app UI without fighting the app for camera access, while the external camera captures what the wearer is seeing in the real world.

## Capturing The Glasses Display

Connect to the glasses over ADB, then start `scrcpy`:

```sh
scrcpy
```

To record directly to a file:

```sh
scrcpy --record glasses-ui.mp4
```

You can also keep the preview window open while recording:

```sh
scrcpy --record glasses-ui.mp4 --no-audio
```

Depending on your setup, you may need the Rokid dev cable or another working ADB connection to the glasses.

## Capturing The Real-World POV

Use a separate camera if you want to show the camera view behind the display. For example:

- A small action camera mounted near your eye line
- A phone mounted on your head or chest
- Any external camera close enough to approximate the wearer's view

Start this recording at the same time as `scrcpy`. A clap, tap, or obvious UI action at the beginning makes it easier to sync both videos later.

## Combining The Videos

You can compose the videos in any editor. For a simple side-by-side layout with `ffmpeg`:

```sh
ffmpeg -i pov.mp4 -i glasses-ui.mp4 \
  -filter_complex "[0:v][1:v]hstack=inputs=2[v]" \
  -map "[v]" -map 0:a? \
  combined-demo.mp4
```

For a picture-in-picture layout:

```sh
ffmpeg -i pov.mp4 -i glasses-ui.mp4 \
  -filter_complex "[1:v]scale=640:-1[ui];[0:v][ui]overlay=W-w-32:32[v]" \
  -map "[v]" -map 0:a? \
  combined-demo.mp4
```

## What About A Single In-App Recording?

The cleanest long-term solution is to implement recording inside the glasses app:

1. Capture the screen or app UI with Android screen-capture APIs
2. Use the app's own camera feed for both app logic and recording
3. Compose the UI and camera feed into one video inside the app

That avoids asking the Hi Rokid app and your own app to own the camera at the same time. It is feasible, but it is more work than the `scrcpy` plus external camera workflow.

## Common Confusion

The display capture and the camera feed are different things. `scrcpy` captures the Android display output. It does not need a separate "UI camera." The conflict happens when two apps both want access to the physical camera feed.

So the practical rule is:

- App does not use the camera: Hi Rokid AR recording may be enough.
- App uses the camera: use `scrcpy` for the display and a separate camera for POV, or build recording into your app.
