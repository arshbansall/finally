const money = new Intl.NumberFormat("en-US", {
  style: "currency",
  currency: "USD",
  minimumFractionDigits: 2,
  maximumFractionDigits: 2,
});

export function formatMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return money.format(value);
}

/** Price without the currency sign, e.g. 1,234.56 */
export function formatPrice(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  return value.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
}

/** Signed money, e.g. +$12.30 / −$4.00 */
export function formatSignedMoney(value: number | null | undefined): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return sign + money.format(Math.abs(value));
}

/** Signed percent, e.g. +1.23% / −0.40% */
export function formatPct(value: number | null | undefined, digits = 2): string {
  if (value == null || !Number.isFinite(value)) return "—";
  const sign = value > 0 ? "+" : value < 0 ? "−" : "";
  return `${sign}${Math.abs(value).toFixed(digits)}%`;
}

/** Share quantities: whole numbers plainly, fractions up to 4 places. */
export function formatQty(value: number): string {
  return value.toLocaleString("en-US", { maximumFractionDigits: 4 });
}

export function trendClass(value: number | null | undefined): string {
  if (value == null || value === 0 || !Number.isFinite(value)) return "text-fg-muted";
  return value > 0 ? "text-up" : "text-down";
}
