// TODO: định dạng số/tiền (USD) cho CostFooter.
export function formatUsd(n: number): string {
  return `$${n.toFixed(4)}`;
}
