export function CrookIcon({ size = 22 }) {
  return (
    <svg
      width={size}
      height={size}
      viewBox="0 0 24 24"
      fill="none"
      stroke="currentColor"
      strokeWidth="2.4"
      strokeLinecap="round"
      aria-hidden="true"
    >
      <path d="M15.5 21.5V8.5C15.5 5.5 13.8 3.5 11.5 3.5C9.2 3.5 7.5 5.5 7.5 8.5V10" />
      <circle cx="7" cy="17" r="1.5" fill="currentColor" stroke="none" />
      <circle cx="11" cy="20" r="1.5" fill="currentColor" stroke="none" />
    </svg>
  )
}

export function Logo() {
  return (
    <span style={{ display: 'flex', alignItems: 'center', gap: '.5rem', fontWeight: 700, fontSize: '1.1rem' }}>
      <CrookIcon />
      Sheppy
    </span>
  )
}
