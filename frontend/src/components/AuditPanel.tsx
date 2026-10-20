import { useEffect, useState } from 'react';
import type { AuditIssue, Deck } from '../types';

type Props = {
  deck: Deck; issues: AuditIssue[]; activeSlideId: string; busy: boolean;
  onClose: () => void; onSlide: (id: string) => void;
  onAudit: (mode: 'rules' | 'contextual' | 'visual') => Promise<void>;
  onFix: (ids: string[]) => Promise<void>; onUndo: () => Promise<void>;
};

export function AuditPanel({deck, issues, activeSlideId, busy, onClose, onSlide, onAudit, onFix, onUndo}: Props) {
  const [selected, setSelected] = useState<string[]>([]);
  useEffect(() => setSelected([]), [deck.id, deck.revision, deck.serverIssues]);
  const canCheck = Boolean(deck.revision && deck.remote && !busy);
  return <aside className="audit-panel" aria-label="Аудит презентации">
    <div className="audit-heading"><h2>Проверка слайдов</h2><button className="icon-button" aria-label="Закрыть проверку" onClick={onClose}>×</button></div>
    <p className="audit-description">Выберите безопасные исправления. Остальные замечания можно оставить или исправить вручную.</p>
    {!deck.remote && <p role="status">Сохраните изменения перед серверной проверкой.</p>}
    <div className="audit-actions">
      <button className="secondary-button" disabled={!canCheck} onClick={()=>void onAudit('rules')}>Проверить геометрию</button>
      <button className="secondary-button" disabled={!canCheck} onClick={()=>void onAudit('contextual')}>Проверить смысл моделью</button>
      <button className="secondary-button" disabled={!canCheck} onClick={()=>void onAudit('visual')}>Проверить изображения моделью</button>
    </div>
    <p className="audit-description">Геометрия и типографика: {deck.remote ? 'расчётная проверка текущей ревизии' : 'доступна после сохранения'}. Текст в браузере проверяется отдельно.</p>
    {(['contextual','visual'] as const).map(mode => {
      const check = deck.remote ? deck.auditChecks?.[mode] : undefined;
      return <p className="audit-check-status" key={mode}>{mode === 'contextual' ? 'Контекстный аудит' : 'Визуальный аудит'}: {check?.status === 'completed' ? `выполнен${check.model ? ` · ${check.provider || ''} / ${check.model}` : ''}` : 'проверка не выполнена'}</p>;
    })}
    <div className={`audit-summary ${issues.length ? 'has-issues' : ''}`}><strong>{issues.length ? `${issues.length} замечаний` : 'Нет замечаний по выполненным проверкам'}</strong></div>
    {issues.map(issue => {
      const index = deck.slides.findIndex(s=>s.id===issue.slideId);
      const fixable = issue.source === 'server' && issue.fixable && deck.remote;
      return <article className={`audit-item ${activeSlideId===issue.slideId?'active':''}`} key={issue.id}>
        <button className="text-button audit-slide-label" onClick={()=>onSlide(issue.slideId)}>Слайд {index+1} · {issue.source==='server' ? issue.category==='contextual' ? 'Модель' : 'Геометрия / правила' : 'Текст / браузер'}</button>
        <strong>{issue.title}</strong><p>{issue.description}</p>
        {!issue.box && <small>Координаты не определены — проверьте содержание указанного слайда.</small>}
        {fixable ? <label className="audit-choice"><input type="checkbox" disabled={!canCheck} checked={selected.includes(issue.id)} onChange={e=>setSelected(ids=>e.target.checked?[...ids,issue.id]:ids.filter(id=>id!==issue.id))}/>Исправить оформление: {issue.rule}</label>
          : <small>{deck.slides[index]?.analysisId ? 'Проверенные факты защищены. Измените источники и пересчитайте.' : 'Автоисправление недоступно. Отредактируйте вручную или оставьте замечание.'}</small>}
      </article>;
    })}
    <button className="primary-button" disabled={!canCheck||!selected.length} onClick={()=>void onFix(selected)}>Применить выбранные ({selected.length})</button>
    {deck.undoRevision && <button className="secondary-button" disabled={!canCheck} onClick={()=>void onUndo()}>Вернуть версию до исправлений</button>}
    <p className="audit-description">Исправления создают новую ревизию. Повторный аудит показывает, какие проблемы остались. Числа, периоды и источники не меняются.</p>
  </aside>;
}

export function AuditOverlay({issues, size}: {issues: AuditIssue[]; size?: Deck['slideSize']}) {
  if (!size) return null;
  return <svg className="audit-overlay" viewBox={`0 0 ${size.width} ${size.height}`} preserveAspectRatio="none" aria-label="Области замечаний аудита">
    {issues.filter(i=>i.box?.length===4).map(issue=><rect key={issue.id} x={issue.box![0]} y={issue.box![1]} width={issue.box![2]} height={issue.box![3]}><title>{issue.title}: {issue.description}</title></rect>)}
  </svg>;
}
