#!/usr/bin/env python
"""

Detect sentence‑level speech boundaries with Silero VAD, run faster‑whisper
transcription on each detected sentence, and *optionally* save every segment
as an individual WAV file.

Usage examples
--------------
    # Just transcribe (default)
    python test_whisper_realtime.py talk.wav

    # Transcribe *and* save chunks
    python test_whisper_realtime.py talk.wav --save-chunks

    # Custom output dir & GPU inference
    python test_whisper_realtime.py talk.wav -o segs --save-chunks \
        --device cuda --model medium
"""

import argparse
import os
import math
import time
from typing import List

import numpy as np
import soundfile as sf
import torch
import torchaudio
from silero_vad import load_silero_vad
from faster_whisper import WhisperModel

# ---------------------- Tunables ------------------------ #
START_SPEECH_PROB = 0.1  # enter "speaking" state
KEEP_SPEECH_PROB = 0.3  # stay in "speaking" state
STOP_SILENCE_MS = 1500  # pause that closes a segment (ms)
MIN_SEGMENT_MS = 500  # ignore segments shorter than this (ms)
# -------------------------------------------------------- #

TARGET_SR = 16_000  # Silero VAD expects 16 kHz mono
FRAME_LEN = 512  # 512 samples ≈ 32 ms @ 16 kHz
STOP_SILENCE_SAMPLES = TARGET_SR * STOP_SILENCE_MS // 1000
MIN_SEGMENT_SAMPLES = TARGET_SR * MIN_SEGMENT_MS // 1000


def resample(block: np.ndarray, orig_sr: int) -> np.ndarray:
    """Return float32 mono block resampled to TARGET_SR."""
    if orig_sr != TARGET_SR:
        block = torchaudio.functional.resample(
            torch.from_numpy(block.T), orig_sr, TARGET_SR
        ).T.numpy()
    if block.ndim > 1:
        block = block.mean(axis=1, keepdims=True)
    return block.astype(np.float32)


def flush(
    buf: List[np.ndarray],
    index: int,
    whisper: WhisperModel,
    save_chunks: bool,
    outdir: str,
) -> int:
    """Transcribe accumulated samples; optionally save. Return next index."""
    if not buf:
        return index

    audio = np.concatenate(buf, axis=0).squeeze()
    if len(audio) < MIN_SEGMENT_SAMPLES:
        return index  # too short → skip

    # --- Whisper transcription ---
    audio_duration = len(audio) / TARGET_SR
    start_time = time.time()
    segments, _ = whisper.transcribe(audio, language="en", beam_size=5)
    transcribe_time = time.time() - start_time
    print(
        f"[TIMING] whisper.transcribe took {transcribe_time:.3f}s for {audio_duration:.2f}s of audio (RTF: {transcribe_time / audio_duration:.2f}x)",
        flush=True,
    )

    for seg in segments:
        txt = seg.text.strip()
        if txt:
            print(f"{txt}", flush=True)

    # --- Optional saving ---
    if save_chunks:
        os.makedirs(outdir, exist_ok=True)
        path = os.path.join(outdir, f"chunk_{index:04d}.wav")
        sf.write(path, audio, TARGET_SR)
        print(f"Saved {path}  ({len(audio) / TARGET_SR:.2f} s)", flush=True)

    return index + 1


def main():
    ap = argparse.ArgumentParser(description="Sentence‑level VAD streamer with Whisper")
    ap.add_argument("wav", help="input .wav file to stream")
    ap.add_argument(
        "-o",
        "--outdir",
        default="tmp-data",
        help="directory for chunk_XXXX.wav when --save-chunks is set",
    )
    ap.add_argument(
        "--save-chunks",
        action="store_true",
        help="save each detected sentence as a WAV file (default: off)",
    )
    ap.add_argument(
        "--device", default="cpu", help="device for Whisper (e.g., cpu, cuda, auto)"
    )
    ap.add_argument("--model", default="small.en", help="Whisper model size")
    ap.add_argument("--compute-type", default="int8", help="Whisper compute_type")
    args = ap.parse_args()

    # Load models
    vad = load_silero_vad()
    whisper = WhisperModel(
        args.model, device=args.device, compute_type=args.compute_type
    )

    with sf.SoundFile(args.wav) as wav:
        native_block = math.ceil((FRAME_LEN * 2) * wav.samplerate / TARGET_SR)
        blocks = wav.blocks(blocksize=native_block, dtype="float32", always_2d=True)

        in_speech = False
        silence = 0
        buf: List[np.ndarray] = []
        chunk_idx = 0

        for raw in blocks:
            block = resample(raw, wav.samplerate)
            samples = block.squeeze()

            for pos in range(0, len(samples), FRAME_LEN):
                frame = samples[pos : pos + FRAME_LEN]
                if len(frame) < FRAME_LEN:
                    frame = np.pad(frame, (0, FRAME_LEN - len(frame)))

                prob = vad(torch.from_numpy(frame), TARGET_SR).item()

                if in_speech:
                    buf.append(frame)
                    if prob > KEEP_SPEECH_PROB:
                        silence = 0
                    else:
                        silence += FRAME_LEN
                        if silence >= STOP_SILENCE_SAMPLES:
                            chunk_idx = flush(
                                buf, chunk_idx, whisper, args.save_chunks, args.outdir
                            )
                            buf.clear()
                            in_speech = False
                            silence = 0
                else:
                    if prob > START_SPEECH_PROB:
                        in_speech = True
                        buf.append(frame)
                        silence = 0

        # Flush trailing audio
        flush(buf, chunk_idx, whisper, args.save_chunks, args.outdir)


if __name__ == "__main__":
    main()
