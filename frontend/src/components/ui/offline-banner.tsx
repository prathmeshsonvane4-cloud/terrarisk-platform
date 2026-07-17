"use client";

import { WifiOff } from "lucide-react";
import { useEffect, useState } from "react";

/**
 * P10 requirement 8 (Offline Recovery) — a persistent, honest "Offline"
 * banner while `navigator.onLine` is false, and nothing more: no queued
 * retries, no fabricated reconnection attempts. React Query's own
 * `refetchOnReconnect` (its default) already re-runs stale queries the
 * moment the browser's `online` event fires, and every mutation in this
 * app is a single explicit user action (never auto-retried), so there is
 * no duplicate-request risk to guard against here beyond simply not firing
 * new requests while offline in the first place — which the browser itself
 * already refuses to do.
 */
export function OfflineBanner() {
  // Start optimistic (true) on the server / first paint — navigator isn't
  // available during SSR, and assuming online avoids a false-positive
  // flash of the banner before hydration can check the real value.
  const [isOnline, setIsOnline] = useState(true);

  useEffect(() => {
    setIsOnline(navigator.onLine);
    function handleOnline() {
      setIsOnline(true);
    }
    function handleOffline() {
      setIsOnline(false);
    }
    window.addEventListener("online", handleOnline);
    window.addEventListener("offline", handleOffline);
    return () => {
      window.removeEventListener("online", handleOnline);
      window.removeEventListener("offline", handleOffline);
    };
  }, []);

  if (isOnline) return null;

  return (
    <div
      role="status"
      aria-live="polite"
      className="flex items-center justify-center gap-2 bg-amber-500/15 px-4 py-1.5 text-xs font-medium text-amber-700 dark:text-amber-400"
    >
      <WifiOff aria-hidden className="size-3.5" />
      You&apos;re offline. TerraRisk will reconnect automatically — nothing you&apos;ve entered is lost.
    </div>
  );
}
