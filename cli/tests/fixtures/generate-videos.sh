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

rotation_tmp="$(mktemp -d)"
trap 'rm -rf -- "$rotation_tmp"' EXIT

ffmpeg -hide_banner -loglevel error -y \
  -f lavfi -i "color=c=black:s=96x64:r=4:d=1" \
  -vf "drawbox=x=0:y=0:w=48:h=32:color=red:t=fill,drawbox=x=48:y=0:w=48:h=32:color=lime:t=fill,drawbox=x=0:y=32:w=48:h=32:color=blue:t=fill,drawbox=x=48:y=32:w=48:h=32:color=yellow:t=fill,format=yuv420p" \
  -c:v mpeg4 \
  -q:v 2 \
  "$rotation_tmp/rotated-quadrants-raw.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -display_rotation:v:0 90 \
  -i "$rotation_tmp/rotated-quadrants-raw.mp4" \
  -c copy \
  "$videos_dir/rotated-quadrants-96x64.mp4"

ffmpeg -hide_banner -loglevel error -y \
  -display_hflip:v:0 \
  -i "$rotation_tmp/rotated-quadrants-raw.mp4" \
  -c copy \
  "$videos_dir/reflected-quadrants-96x64.mp4"
