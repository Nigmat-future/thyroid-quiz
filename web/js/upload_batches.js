const MAX_FILES_PER_UPLOAD_REQUEST = 80;
const MAX_BYTES_PER_UPLOAD_REQUEST = 64 * 1024 * 1024;

export const MAX_PENDING_PREVIEW_ROWS = 200;

export function createPendingItem(file, gt) {
  return { file, gt, previewUrl: null };
}

export function revokePendingItem(item) {
  if (item?.previewUrl) URL.revokeObjectURL(item.previewUrl);
}

export function clearPendingItems(items) {
  for (const item of items) revokePendingItem(item);
}

export function pendingPreviewHtml(item, index) {
  if (index >= MAX_PENDING_PREVIEW_ROWS) {
    return `<span class="pending-thumb" aria-hidden="true">${index + 1}</span>`;
  }
  if (!item.previewUrl) item.previewUrl = URL.createObjectURL(item.file);
  return `<img src="${item.previewUrl}" alt="预览">`;
}

export function nextUploadChunk(pending) {
  const chunk = [];
  let bytes = 0;
  for (const entry of pending.entries()) {
    const [, item] = entry;
    const wouldOverflow = chunk.length > 0 && (
      chunk.length >= MAX_FILES_PER_UPLOAD_REQUEST
      || bytes + item.file.size > MAX_BYTES_PER_UPLOAD_REQUEST
    );
    if (wouldOverflow) break;
    chunk.push(entry);
    bytes += item.file.size;
    if (chunk.length >= MAX_FILES_PER_UPLOAD_REQUEST || bytes >= MAX_BYTES_PER_UPLOAD_REQUEST) {
      break;
    }
  }
  return chunk;
}

export async function uploadQuestionChunk(code, chunk) {
  const fd = new FormData();
  const truths = [];
  for (const [, item] of chunk) {
    fd.append("files", item.file);
    truths.push(item.gt);
  }
  fd.append("ground_truths", JSON.stringify(truths));

  const res = await fetch(`/api/tasks/${encodeURIComponent(code)}/questions/upload`, {
    method: "POST",
    credentials: "same-origin",
    body: fd,
  });
  if (!res.ok) {
    let msg = `上传失败 (${res.status})`;
    try { const j = await res.json(); if (j.detail) msg = j.detail; } catch {}
    throw new Error(msg);
  }
  return res.json();
}
