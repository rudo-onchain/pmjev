import { Panel } from './ui/Panel';

function Bar({ className }: {className: string;}) {
  return <div className={`rounded-md bg-raised motion-safe:animate-pulse ${className}`} />;
}

export function DashboardSkeleton() {
  return (
    <div aria-busy="true" aria-live="polite" className="grid grid-cols-1 gap-4 lg:grid-cols-12 lg:gap-5">
      <span className="sr-only">Loading portfolio…</span>
      <Panel as="div" className="flex flex-col lg:col-span-8 lg:flex-row">
        <div className="p-5 sm:p-6 lg:w-[300px] lg:shrink-0 lg:border-r lg:border-line-soft">
          <Bar className="h-4 w-32" />
          <Bar className="mt-4 h-14 w-56" />
          <div className="mt-5 flex gap-8">
            <Bar className="h-10 w-24" />
            <Bar className="h-10 w-20" />
          </div>
          <Bar className="mt-8 h-4 w-full" />
          <Bar className="mt-2 h-4 w-full" />
          <Bar className="mt-2 h-4 w-full" />
        </div>
        <div className="hidden flex-1 p-6 lg:block">
          <div className="flex justify-between">
            <Bar className="h-9 w-40" />
            <Bar className="h-8 w-44" />
          </div>
          <Bar className="mt-4 h-[220px] w-full" />
        </div>
      </Panel>
      <Panel as="div" className="p-5 sm:p-6 lg:col-span-4">
        <Bar className="h-4 w-28" />
        <div className="mt-5 grid grid-cols-2 gap-4">
          <Bar className="h-12" />
          <Bar className="h-12" />
        </div>
        <Bar className="mt-5 h-1.5 w-full" />
        <Bar className="mt-10 h-4 w-full" />
        <Bar className="mt-3 h-4 w-full" />
      </Panel>
      <Panel as="div" className="p-6 lg:col-span-8">
        <Bar className="h-4 w-36" />
        {Array.from({ length: 3 }).map((_, i) =>
        <Bar key={i} className="mt-5 h-10 w-full" />
        )}
      </Panel>
      <Panel as="div" className="p-6 lg:col-span-4">
        <Bar className="h-4 w-32" />
        {Array.from({ length: 4 }).map((_, i) =>
        <Bar key={i} className="mt-5 h-9 w-full" />
        )}
      </Panel>
      <Panel as="div" className="p-6 lg:col-span-12">
        <Bar className="h-4 w-40" />
        {Array.from({ length: 4 }).map((_, i) =>
        <Bar key={i} className="mt-5 h-10 w-full" />
        )}
      </Panel>
    </div>);

}