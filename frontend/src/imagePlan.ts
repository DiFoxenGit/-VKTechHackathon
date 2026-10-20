import type { ImageGeneration } from './types';

export function normalizeImageGeneration(value: unknown): ImageGeneration | undefined {
  if (!value || typeof value !== 'object') return;
  const v = value as Record<string, unknown>;
  if (typeof v.status !== 'string' || !['not_requested','ready','partial','unavailable','failed'].includes(v.status) || typeof v.message !== 'string') return;
  const result: ImageGeneration = {status: v.status as ImageGeneration['status'], message: v.message.slice(0, 2000)};
  for (const key of ['count', 'requested_count'] as const) {
    if (typeof v[key] === 'number' && Number.isInteger(v[key]) && v[key] >= 0 && v[key] <= 12) result[key] = v[key];
  }
  if (Array.isArray(v.quality_checks)) {
    result.quality_checks = v.quality_checks.slice(0, 12).flatMap(raw => {
      if (!raw || typeof raw !== 'object') return [];
      const q = raw as Record<string, unknown>;
      if (typeof q.id !== 'string' || q.scope !== 'visible_text_only' ||
          !['passed','rejected','unavailable','failed'].includes(String(q.status))) return [];
      const attempted = q.attempted === true;
      const has_text = typeof q.has_text === 'boolean' ? q.has_text : null;
      let status = q.status as NonNullable<ImageGeneration['quality_checks']>[number]['status'];
      if ((status === 'passed' && (!attempted || has_text !== false)) ||
          (status === 'rejected' && (!attempted || has_text !== true))) status = 'failed';
      return [{id:q.id.slice(0,100),scope:'visible_text_only' as const,status,attempted,has_text,
        ...(typeof q.model === 'string' ? {model:q.model.slice(0,120)} : {})}];
    });
  }
  if (v.plan && typeof v.plan === 'object') {
    const plan = v.plan as Record<string, unknown>;
    if (typeof plan.reason === 'string' && Array.isArray(plan.images) && plan.images.length <= 12) {
      const images: NonNullable<ImageGeneration['plan']>['images'] = [];
      for (const raw of plan.images) {
        if (!raw || typeof raw !== 'object') return result;
        const i = raw as Record<string, unknown>;
        if (typeof i.slide !== 'number' || !Number.isInteger(i.slide) || i.slide < 1 || i.slide > 30 ||
            typeof i.prompt !== 'string' || !['left','right'].includes(String(i.placement)) || !['photo','illustration'].includes(String(i.style))) return result;
        images.push({slide: i.slide, prompt: i.prompt.slice(0, 1600), placement: i.placement as 'left' | 'right', style: i.style as 'photo' | 'illustration'});
      }
      result.plan = {reason: plan.reason.slice(0, 600), images};
    }
  }
  return result;
}
