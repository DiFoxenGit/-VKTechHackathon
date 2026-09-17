/**
 * Тема интерфейса: светлая, тёмная или системная.
 *
 * Выбор хранится в localStorage и ставится атрибутом на <html> ещё до первого
 * рендера (см. index.html), чтобы страница не мигала светлым фоном.
 */

export type Theme = 'light' | 'dark' | 'system';

const KEY = 'designer-theme';

export function readTheme(): Theme {
  try {
    const value = localStorage.getItem(KEY);
    return value === 'light' || value === 'dark' ? value : 'system';
  } catch {
    // Приватный режим или заблокированное хранилище: работаем по системной.
    return 'system';
  }
}

export function applyTheme(theme: Theme) {
  const root = document.documentElement;
  if (theme === 'system') root.removeAttribute('data-theme');
  else root.setAttribute('data-theme', theme);
  try {
    if (theme === 'system') localStorage.removeItem(KEY);
    else localStorage.setItem(KEY, theme);
  } catch {
    // Не сохранили — не страшно, тема действует до перезагрузки.
  }
}

export function systemIsDark(): boolean {
  return window.matchMedia?.('(prefers-color-scheme: dark)').matches ?? false;
}
