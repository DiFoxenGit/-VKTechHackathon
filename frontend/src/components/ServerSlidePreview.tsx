import { useState } from 'react';
import { isPreviewReady } from '../services/previewReady';

export function ServerSlidePreview({url,title,miniature}: {url:string;title:string;miniature:boolean}) {
  const [attempt,setAttempt] = useState(0);
  const [loaded,setLoaded] = useState(() => isPreviewReady(url) ? url : '');
  const [failed,setFailed] = useState('');
  const source = `${url}${attempt ? `&retry=${attempt}` : ''}`;
  return <div className={`slide-canvas server-canvas ${miniature?'miniature':''}`} aria-busy={loaded!==source && failed!==source}>
    {failed!==source && <img loading={miniature?'lazy':'eager'} src={source} alt={title} onLoad={()=>setLoaded(source)} onError={()=>setFailed(source)}/>}
    {loaded!==source && failed!==source && <div className="preview-state" role="status">Готовим предпросмотр…</div>}
    {failed===source && <div className="preview-state" role="status"><span>Не удалось загрузить предпросмотр</span>{!miniature && <><small>Проверьте подключение. Экспорт доступен через «Скачать».</small><button className="secondary-button" onClick={()=>setAttempt(n=>n+1)}>Повторить</button></>}</div>}
  </div>;
}
