# Rokid Feature Demo

Rokid Feature Demo is a Rokid Glasses app for testing device features and common implementation patterns.

See [AGENTS.md](./AGENTS.md) for project details.

## Control Mapping

| Intent                       | Rokid Glasses touchpad (`KeyEvent`) | Voice command | Android touchscreen |
| ---------------------------- | ----------------------------------- | ------------- | ------------------- |
| Select / OK                  | Tap (`KEYCODE_ENTER`)               | `select`      | Tap                 |
| Back / cancel                | Double tap (`KEYCODE_BACK`)         | `back`        | Double tap          |
| Move focus to the right/down | Swipe forward (`KEYCODE_DPAD_DOWN`) | `next`        | Swipe right         |
| Move focus to the left/up    | Swipe back (`KEYCODE_DPAD_UP`)      | `previous`    | Swipe left          |

`Android touchscreen` applies to Android phones and the Android emulator, where a Rokid-style touchpad is not available.

Rokid Glasses are still the best way to test the app, but a normal Android phone also works. The emulator should be usable as well, though it currently has some restrictions; see below.

## Vosk Model Setup

Vosk is used for voice commands. Install the model before building:

```bash
./scripts/download_vosk_model.sh
```

## Emulator Setup

The configuration below is one example of an Android emulator setup. You may need to adjust it for your local environment.

Install the system image and create an AVD:

```bash
sdkmanager "system-images;android-36.1;google_apis;arm64-v8a"
avdmanager create avd \
  -n glass_480x640 \
  -k "system-images;android-36.1;google_apis;arm64-v8a" \
  -d "pixel_9a"
```

Edit `~/.android/avd/glass_480x640.avd/config.ini` and set:

```ini
hw.lcd.width=480
hw.lcd.height=640
hw.lcd.density=240
hw.audioOutput=yes
```

Start the emulator with the software-backed emulated rear camera:

```bash
emulator -avd glass_480x640 -camera-back emulated
```

Other `-camera-back` sources may or may not work depending on your emulator setup: `webcam0`, `virtualscene`, `videoplayback`.

Host microphone passthrough may be available if you enable `hw.audioInput=yes` in the config, start the emulator with `-allow-host-audio`, and run `adb emu avd hostmicon`.

In my current setup, camera and microphone passthrough are not stable or performant enough, so I do not rely on emulator checks for them.
