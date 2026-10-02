// Starting a browser download does not confirm that the user saved the file.
export function downloadBlob(blob: Blob, filename: string): void {
  const url = URL.createObjectURL(blob);
  let anchor: HTMLAnchorElement | undefined;
  try {
    anchor = document.createElement("a");
    anchor.href = url;
    anchor.download = filename;
    anchor.hidden = true;
    document.body.appendChild(anchor);
    anchor.click();
  } finally {
    anchor?.remove();
    // Give the browser time to start reading the object URL before releasing it.
    setTimeout(() => URL.revokeObjectURL(url), 10000);
  }
}
