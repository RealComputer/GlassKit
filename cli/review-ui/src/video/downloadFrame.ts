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

export function downloadFrameUrl(
  url: string,
  filename: string,
  ownerDocument: Document = document,
): void {
  const link = ownerDocument.createElement("a");
  link.href = url;
  link.download = filename;
  link.hidden = true;
  ownerDocument.body.append(link);
  link.click();
  link.remove();
}
