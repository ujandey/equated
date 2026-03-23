/**
 * Utility / formatting helpers.
 */

/** Format a date string to relative time (e.g., "2 hours ago") */
export function timeAgo(dateStr: string): string {
  const date = new Date(dateStr);
  const now = new Date();
  const seconds = Math.floor((now.getTime() - date.getTime()) / 1000);

  const intervals: [number, string][] = [
    [31536000, "year"],
    [2592000, "month"],
    [86400, "day"],
    [3600, "hour"],
    [60, "minute"],
  ];

  for (const [secs, label] of intervals) {
    const count = Math.floor(seconds / secs);
    if (count >= 1) {
      return `${count} ${label}${count > 1 ? "s" : ""} ago`;
    }
  }
  return "just now";
}

/** Truncate text with ellipsis */
export function truncate(text: string, maxLength: number): string {
  if (text.length <= maxLength) return text;
  return text.slice(0, maxLength - 3) + "...";
}

/** Format number with commas (1000 → "1,000") */
export function formatNumber(n: number): string {
  return n.toLocaleString();
}

/** Format currency in INR */
export function formatINR(amount: number): string {
  return `₹${amount.toLocaleString("en-IN")}`;
}
