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

I currently combine one UI capture video and one POV camera video with `ffmpeg`. First, I manually review both recordings, identify the exact timing offset, and trim the inputs so they start in sync. In the example below, those synced inputs are `pov-trim.mp4` and `ui-trim.mp4`.

```bash
ffmpeg -i pov-trim.mp4 -i ui-trim.mp4 -filter_complex "\
[1:v]pad=iw+4:ih+4:(ow-iw)/2:(oh-ih)/2:color=white,\
format=yuva444p,\
lumakey=threshold=0:tolerance=0.22:softness=0.01,\
format=rgba,\
lutrgb=r=0:g=255:b=0[ui0];\
[ui0][0:v]scale2ref=w=oh*mdar:h='min(ih-100,(iw-50)/mdar)':flags=lanczos[ui][pov];\
[pov][ui]overlay=50:50:alpha=straight:format=auto:shortest=1[v]" \
-map "[v]" -map "0:a?" \
-c:v libx264 -crf 18 -preset medium -pix_fmt yuv420p \
-c:a aac -b:a 192k -ar 48000 -ac 2 \
-movflags +faststart pov-and-ui.mp4
```

This overlays the UI capture near the top-left of the POV video. The `lumakey` and `lutrgb` steps make the black UI capture background transparent and recolor the UI overlay green so it is visible against the camera footage.

## POV Recording Gear

My current POV recording setup is:

1. DJI Osmo Nano
2. DJI Osmo Nano headband accessory
3. DJI Mic Mini

The DJI Osmo Nano has a built-in mic, which is enough for my voice and environmental sound. I add the DJI Mic Mini because the glasses speaker audio comes from the temple area and is easy to miss. I attach the mic around my ear so it captures the glasses audio more clearly.

You do not need this exact setup. This is just how I recorded demos like [this example video](https://www.youtube.com/watch?v=oqEA6t2etZo).

## What About A Single In-App Recording?

The cleanest long-term solution is to implement recording inside the glasses app:

1. Capture the screen or app UI with Android screen-capture APIs
2. Use the app's own camera feed for both app logic and recording
3. Compose the UI and camera feed into one video inside the app

That avoids asking the Hi Rokid app and your own app to use the camera at the same time.

This is on our roadmap.
