#!/usr/bin/env bash
set -euo pipefail

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
videos_dir="$script_dir/videos"
mkdir -p "$videos_dir"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=black:s=64x64:r=4:d=1" \
  -f lavfi -i "color=c=white:s=64x64:r=4:d=1" \
  -filter_complex "[0:v][1:v]concat=n=2:v=1:a=0,format=yuv420p[v]" \
  -map "[v]" \
  -c:v mpeg4 \
  -q:v 5 \
  "$videos_dir/two-state-64x64.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=black:s=64x64:r=2:d=2" \
  -vf "setpts=PTS+10/TB,format=yuv420p" \
  -c:v mpeg4 \
  -q:v 5 \
  "$videos_dir/offset-start-64x64.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "testsrc2=s=96x128:r=4:d=1" \
  -vf "format=yuv420p" \
  -c:v mpeg4 \
  -q:v 5 \
  "$videos_dir/portrait-96x128.mp4"
