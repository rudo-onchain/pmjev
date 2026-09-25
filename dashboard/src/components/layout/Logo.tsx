
export function Logo() {
  return (
    <div className="flex items-center gap-2.5">
      <span className="flex h-8 w-8 items-center justify-center rounded-lg bg-ink" aria-hidden="true">
        <svg viewBox="0 0 20 20" className="h-4 w-4" fill="none">
          <path
            d="M3 14.5 7.5 9l3 3L17 5"
            stroke="#111317"
            strokeWidth="2.2"
            strokeLinecap="round"
            strokeLinejoin="round" />
          
        </svg>
      </span>
      <span className="text-[15px] font-semibold tracking-tight text-ink">PMJEV</span>
    </div>);

}