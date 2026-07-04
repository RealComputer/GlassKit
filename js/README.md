# @glasskit.ai/create

WIP create package for GlassKit starter projects.

This first version only copies the Rokid Glasses starter app. The interface and generated project are work in progress and may change before this package is advertised more widely.

## Usage

```bash
npm create @glasskit.ai
npm create @glasskit.ai my-rokid-app
```

The default target directory is `rokid-starter`.

After generation:

```bash
cd rokid-starter
./gradlew :app:assembleDebug
adb install -r app/build/outputs/apk/debug/app-debug.apk
adb shell am start -n com.example.rokidhello/.MainActivity
```

## Development

The starter template is generated at pack time from `../skills/glasskit/assets/rokid-hello-world` into `dist/template/rokid-hello-world`. The generated `dist/` directory is not committed.
