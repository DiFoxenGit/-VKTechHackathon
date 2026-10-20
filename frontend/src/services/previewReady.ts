// Keep decoded previews alive until the editor mounts, avoiding a second loading flash.
const decoded = new Map<string, HTMLImageElement>();
export function isPreviewReady(url: string): boolean { return decoded.has(url); }

export function preparePreview(url: string | undefined, signal?: AbortSignal): Promise<void> {
  if (signal?.aborted) return Promise.reject(new DOMException('Aborted', 'AbortError'));
  if (!url || decoded.has(url)) return Promise.resolve();
  return new Promise((resolve, reject) => {
    const image = new Image();
    let settled = false;
    const finish = (error?: Error) => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timer);
      signal?.removeEventListener('abort', abort);
      image.onload = null; image.onerror = null;
      if (error) { image.src = ''; reject(error); }
      else {
        decoded.set(url, image);
        if (decoded.size > 32) decoded.delete(decoded.keys().next().value!);
        resolve();
      }
    };
    const abort = () => finish(new DOMException('Aborted', 'AbortError'));
    const timer = window.setTimeout(() => finish(new Error('Не удалось дождаться обложки.')), 60_000);
    signal?.addEventListener('abort', abort, {once:true});
    image.onerror = () => finish(new Error('Не удалось загрузить обложку.'));
    image.onload = async () => {
      try {
        await image.decode();
        if (!image.naturalWidth) throw new Error('Обложка недоступна.');
        finish();
      } catch { finish(new Error('Не удалось подготовить обложку.')); }
    };
    image.src = url;
  });
}
