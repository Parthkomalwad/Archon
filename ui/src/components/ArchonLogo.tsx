interface ArchonLogoProps {
  size?: number;
  className?: string;
}

export default function ArchonLogo({ size = 36, className = "" }: ArchonLogoProps) {
  return (
    <svg width={size} height={size} viewBox="0 0 40 40" fill="none" xmlns="http://www.w3.org/2000/svg" className={className}>
      <defs>
        <linearGradient id="hexGrad" x1="0" y1="0" x2="40" y2="40" gradientUnits="userSpaceOnUse">
          <stop offset="0%" stopColor="#111827"/>
          <stop offset="100%" stopColor="#1E293B"/>
        </linearGradient>
        <filter id="glow">
          <feGaussianBlur stdDeviation="1.5" result="coloredBlur"/>
          <feMerge><feMergeNode in="coloredBlur"/><feMergeNode in="SourceGraphic"/></feMerge>
        </filter>
      </defs>
      <path d="M20 3L35 11.5V28.5L20 37L5 28.5V11.5L20 3Z" fill="url(#hexGrad)"/>
      <path d="M20 3L35 11.5V28.5L20 37L5 28.5V11.5L20 3Z" stroke="#6366F1" strokeWidth="1.5" filter="url(#glow)"/>
      <path d="M13 28L20 12L27 28" stroke="#6366F1" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" filter="url(#glow)"/>
      <path d="M15.5 22H24.5" stroke="#6366F1" strokeWidth="2" strokeLinecap="round" filter="url(#glow)"/>
    </svg>
  );
}
