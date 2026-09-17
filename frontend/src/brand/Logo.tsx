/** Знак сервиса: слайд с направляющими и акцентной колонкой. */

export function Logo({ size = 28 }: { size?: number }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 32 32"
      role="img"
      aria-label="Слайдер"
      fill="none"
    >
      <rect x="1.5" y="4.5" width="29" height="23" rx="5" fill="var(--brand-500)" />
      <rect x="6" y="9" width="12" height="2.6" rx="1.3" fill="var(--on-brand)" opacity="0.95" />
      <rect x="6" y="14" width="9" height="2.2" rx="1.1" fill="var(--on-brand)" opacity="0.7" />
      <rect x="6" y="18.4" width="6" height="2.2" rx="1.1" fill="var(--on-brand)" opacity="0.5" />
      <rect x="21" y="9" width="5" height="11.6" rx="2.2" fill="var(--accent-500)" />
    </svg>
  );
}

export function Wordmark() {
  return (
    <span className="wordmark">
      <Logo />
      <span>
        Слайдер<span className="wordmark-dot">.</span>
      </span>
    </span>
  );
}
