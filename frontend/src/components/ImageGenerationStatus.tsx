import type { ImageGeneration } from '../types';
import { imageText } from '../locales/images';

export function ImageGenerationStatus({value, disabled, onRetry, language = 'ru'}: {
  value: ImageGeneration; disabled: boolean; onRetry: () => void; language?: 'ru' | 'en';
}) {
  const text = imageText[language];
  return <section className={`image-generation-status ${value.status}`} role="status">
    <strong>{text.title}</strong><p>{value.status === 'ready' || value.status === 'partial' ? text[value.status] : value.message}</p>
    {value.count !== undefined && <p>{text.count}: {value.count} {text.of} {value.requested_count ?? value.count}</p>}
    {value.plan && <details><summary>{text.plan}</summary><p>{value.plan.reason}</p><ol>{value.plan.images.map((item, i) =>
      <li key={i}>{text.slide} {item.slide}, {text[item.placement]}: {item.prompt}</li>)}</ol></details>}
    {['failed', 'unavailable'].includes(value.status) && <button className="secondary-button" disabled={disabled} onClick={onRetry}>{text.retry}</button>}
  </section>;
}
