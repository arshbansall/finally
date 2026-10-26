import type { ReactNode } from "react";

interface PanelProps {
  title: string;
  /** Right-aligned header content (counts, controls). */
  aside?: ReactNode;
  className?: string;
  bodyClassName?: string;
  children: ReactNode;
  testId?: string;
  /** Extra data-* attributes for the section (e.g. data-ticker). */
  data?: Record<`data-${string}`, string | number | undefined>;
}

export default function Panel({ title, aside, className = "", bodyClassName = "", children, testId, data }: PanelProps) {
  return (
    <section className={`flex h-full min-h-0 min-w-0 flex-col bg-ink-900 ${className}`} data-testid={testId} {...data}>
      <header className="flex h-8 shrink-0 items-center justify-between gap-2 border-b border-line px-3">
        <h2 className="narrow text-[12px] font-semibold tracking-wide text-fg-muted">{title}</h2>
        {aside ? <div className="flex items-center gap-2 text-2xs text-fg-faint">{aside}</div> : null}
      </header>
      <div className={`min-h-0 flex-1 ${bodyClassName}`}>{children}</div>
    </section>
  );
}
