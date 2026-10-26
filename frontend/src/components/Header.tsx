import type { ConnectionStatus } from "@/lib/types";
import { formatMoney, formatPct, formatSignedMoney, trendClass } from "@/lib/format";

interface HeaderProps {
  totalValue: number | null;
  cash: number | null;
  invested: number | null;
  unrealizedPnl: number | null;
  unrealizedPnlPct: number | null;
  status: ConnectionStatus;
}

const STATUS_STYLE: Record<ConnectionStatus, { color: string; label: string }> = {
  connected: { color: "bg-up", label: "Live" },
  reconnecting: { color: "bg-accent dot-pulse", label: "Reconnecting" },
  disconnected: { color: "bg-down", label: "Offline" },
};

export default function Header({ totalValue, cash, invested, unrealizedPnl, unrealizedPnlPct, status }: HeaderProps) {
  const s = STATUS_STYLE[status];
  return (
    <header className="flex h-14 shrink-0 items-stretch border-b border-line bg-ink-950">
      <div className="flex items-center gap-2 border-r border-line px-4">
        <span className="h-5 w-1.5 rounded-sm bg-accent" aria-hidden />
        <span className="text-[17px] font-bold tracking-tight text-fg">
          Fin<span className="text-accent">Ally</span>
        </span>
      </div>

      <dl className="flex min-w-0 flex-1 items-stretch overflow-x-auto">
        <div className="flex flex-col justify-center border-r border-line px-5">
          <dt className="narrow text-2xs text-fg-faint">Portfolio value</dt>
          <dd className="num text-[20px] font-semibold leading-6 text-fg" data-testid="header-total-value">
            {formatMoney(totalValue)}
          </dd>
        </div>
        <div className="flex flex-col justify-center border-r border-line px-5">
          <dt className="narrow text-2xs text-fg-faint">Cash</dt>
          <dd className="num text-[15px] font-medium leading-6 text-fg" data-testid="header-cash">
            {formatMoney(cash)}
          </dd>
        </div>
        <div className="flex flex-col justify-center border-r border-line px-5">
          <dt className="narrow text-2xs text-fg-faint">Invested</dt>
          <dd className="num text-[15px] font-medium leading-6 text-fg" data-testid="header-invested">
            {formatMoney(invested)}
          </dd>
        </div>
        <div className="flex flex-col justify-center border-r border-line px-5">
          <dt className="narrow text-2xs text-fg-faint">Unrealized P&amp;L</dt>
          <dd className={`num text-[15px] font-medium leading-6 ${trendClass(unrealizedPnl)}`} data-testid="header-pnl">
            {formatSignedMoney(unrealizedPnl)}
            <span className="ml-1.5 text-[12px]">{formatPct(unrealizedPnlPct)}</span>
          </dd>
        </div>
      </dl>

      <div className="flex items-center gap-2 px-4" title={`Price stream: ${s.label.toLowerCase()}`}>
        <span
          className={`inline-block h-2.5 w-2.5 rounded-full ${s.color}`}
          data-testid="connection-status"
          data-status={status}
          role="status"
          aria-label={`Price stream ${status}`}
        />
        <span className="narrow text-[12px] text-fg-muted">{s.label}</span>
      </div>
    </header>
  );
}
