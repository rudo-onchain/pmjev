import { motion } from 'framer-motion';

interface SegmentedControlProps<T extends string> {
  options: readonly T[];
  value: T;
  onChange: (value: T) => void;
  label: string;
  layoutId: string;
  className?: string;
}

export function SegmentedControl<T extends string>({
  options,
  value,
  onChange,
  label,
  layoutId,
  className = ''
}: SegmentedControlProps<T>) {
  return (
    <div
      role="radiogroup"
      aria-label={label}
      className={`inline-flex items-center gap-0.5 rounded-lg border border-line bg-canvas p-0.5 ${className}`}>
      
      {options.map((option) => {
        const active = option === value;
        return (
          <button
            key={option}
            type="button"
            role="radio"
            aria-checked={active}
            onClick={() => onChange(option)}
            className={`relative whitespace-nowrap rounded-md px-3 py-1.5 text-xs font-medium transition-colors duration-150 focus-visible:outline-none focus-visible:ring-2 focus-visible:ring-info/60 ${
            active ? 'text-ink' : 'text-muted hover:text-ink'}`
            }>
            
            {active &&
            <motion.span
              layoutId={layoutId}
              className="absolute inset-0 rounded-md border border-line bg-raised"
              transition={{ type: 'tween', duration: 0.18, ease: [0.23, 1, 0.32, 1] }} />

            }
            <span className="relative">{option}</span>
          </button>);

      })}
    </div>);

}