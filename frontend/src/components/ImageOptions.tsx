import { imageText } from '../locales/images';

export function ImageOptions({value, disabled, onChange, language = 'ru'}: {
  value?: boolean; disabled: boolean; onChange: (value: boolean | undefined) => void; language?: 'ru' | 'en';
}) {
  const text = imageText[language];
  return <div className="image-options"><label htmlFor="image-mode">{text.label}</label>
    <select id="image-mode" aria-describedby="image-mode-hint" value={value === undefined ? 'auto' : value ? 'on' : 'off'}
      disabled={disabled} onChange={e => onChange(e.target.value === 'auto' ? undefined : e.target.value === 'on')}>
      <option value="auto">{text.auto}</option><option value="on">{text.on}</option><option value="off">{text.off}</option>
    </select><small id="image-mode-hint">{text.hint}</small></div>;
}
