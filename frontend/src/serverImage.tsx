/** Картинки с сервера: миниатюры слайдов и обложки шаблонов.
 *
 *  Идут через api.download, потому что API может требовать токен, а <img src>
 *  заголовков не передаёт. Одна и та же миниатюра нужна в ленте, на карточке
 *  варианта и в проектах — поэтому blob-ссылки живут в общем кеше, а не в
 *  компоненте, и не создаются заново при каждой отрисовке.
 */
import { useEffect, useState } from 'react';
import type { ReactNode } from 'react';
import { api } from './services/api';

/** Сколько миниатюр держать в памяти: весь рабочий набор экрана с запасом. */
const CACHE_LIMIT = 150;
const cache = new Map<string, string>();
const pending = new Map<string, Promise<string>>();

function remember(path: string, url: string) {
  cache.set(path, url);
  if (cache.size <= CACHE_LIMIT) return;
  const oldest = cache.keys().next().value;
  if (oldest === undefined) return;
  URL.revokeObjectURL(cache.get(oldest)!);
  cache.delete(oldest);
}

function load(path: string): Promise<string> {
  const ready = cache.get(path);
  if (ready) return Promise.resolve(ready);
  let request = pending.get(path);
  if (!request) {
    request = api.download(path)
      .then(blob => {
        const url = URL.createObjectURL(blob);
        remember(path, url);
        return url;
      })
      .finally(() => pending.delete(path));
    pending.set(path, request);
  }
  return request;
}

/** Blob-ссылка на картинку или пустая строка, пока она грузится или недоступна. */
export function useServerImage(path: string | null): string {
  const [url, setUrl] = useState(() => (path && cache.get(path)) || '');
  useEffect(() => {
    if (!path) { setUrl(''); return; }
    let live = true;
    setUrl(cache.get(path) || '');
    load(path)
      .then(value => { if (live) setUrl(value); })
      .catch(() => { if (live) setUrl(''); });
    return () => { live = false; };
  }, [path]);
  return url;
}

/** Настоящая картинка с сервера; пока её нет — запасной вид. */
export function ServerImage({ path, alt, fallback, className }: {
  path: string | null;
  alt: string;
  fallback: ReactNode;
  className?: string;
}) {
  const url = useServerImage(path);
  if (!url) return <>{fallback}</>;
  return <img className={className} src={url} alt={alt} draggable={false} />;
}
