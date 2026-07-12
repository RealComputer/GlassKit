export function frameDownloadFilename(caseName: string, timestamp: number): string {
  const safeCaseName = caseName
    .normalize("NFKC")
    .trim()
    .replace(/[^\p{Letter}\p{Number}._-]+/gu, "-")
    .replace(/^[.-]+|[.-]+$/g, "")
    .slice(0, 80);
  const safeTimestamp = Math.max(0, Number.isFinite(timestamp) ? timestamp : 0);
  return `${safeCaseName || "frame"}-${safeTimestamp.toFixed(3)}s.png`;
}

export function isVideoFrameReady(video: HTMLVideoElement): boolean {
  return (
    !video.seeking &&
    video.readyState >= HTMLMediaElement.HAVE_CURRENT_DATA &&
    video.videoWidth > 0 &&
    video.videoHeight > 0
  );
}

export async function downloadVideoFrame(video: HTMLVideoElement, filename: string): Promise<void> {
  if (!isVideoFrameReady(video)) {
    throw new Error("The current video frame is not ready to download.");
  }

  const ownerDocument = video.ownerDocument;
  const canvas = ownerDocument.createElement("canvas");
  canvas.width = video.videoWidth;
  canvas.height = video.videoHeight;
  const context = canvas.getContext("2d");
  if (!context) throw new Error("The browser could not create an image canvas.");
  context.drawImage(video, 0, 0, canvas.width, canvas.height);

  const blob = await new Promise<Blob>((resolve, reject) => {
    canvas.toBlob((result) => {
      if (result) resolve(result);
      else reject(new Error("The browser could not encode the current frame."));
    }, "image/png");
  });
  const url = URL.createObjectURL(blob);
  const link = ownerDocument.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  ownerDocument.body.append(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 0);
}
