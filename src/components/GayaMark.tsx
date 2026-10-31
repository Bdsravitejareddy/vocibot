// Gaya's mark: a single leaf on a soft sage-to-mint tile, with a calm wave for the voice it listens to.
export function GayaMark({ size = 36 }: { size?: number }) {
  return <svg width={size} height={size} viewBox="0 0 48 48" role="img" aria-label="Gaya">
    <defs>
      <linearGradient id="gaya-tile" x1="0" y1="0" x2="1" y2="1">
        <stop offset="0" stopColor="#cfe8d5" />
        <stop offset="1" stopColor="#8fc7a4" />
      </linearGradient>
      <linearGradient id="gaya-leaf" x1="0" y1="1" x2="1" y2="0">
        <stop offset="0" stopColor="#2f7a55" />
        <stop offset="1" stopColor="#5aa77b" />
      </linearGradient>
    </defs>
    <rect width="48" height="48" rx="14" fill="url(#gaya-tile)" />
    <path d="M14 34c0-11 8-20 21-21 0 13-8 21-19 21z" fill="url(#gaya-leaf)" />
    <path d="M16 32c4-5 9-9 15-13" stroke="#e6f4ea" strokeWidth="1.6" strokeLinecap="round" fill="none" />
    <path d="M10 39c3-2 6-2 9 0s6 2 9 0 6-2 9 0" stroke="#2f7a55" strokeOpacity=".55" strokeWidth="1.6" strokeLinecap="round" fill="none" />
  </svg>;
}
