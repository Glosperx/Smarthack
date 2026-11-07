import { useEffect, useState } from 'react';

/**
 * Calculates remaining seconds until the next maintenance prediction run slot.
 * The backend worker runs on an aligned schedule: default interval 10m, offset 2m (:02, :12, :22, ...).
 */
export function getSecondsUntilNextRun(
  now = new Date(),
  intervalMin = 10,
  offsetMin = 2
): number {
  const midnight = new Date(now);
  midnight.setHours(0, 0, 0, 0);
  const elapsedMin = (now.getTime() - midnight.getTime()) / 60000;
  const k = Math.max(Math.floor((elapsedMin - offsetMin) / intervalMin) + 1, 0);
  const nextMin = offsetMin + k * intervalMin;

  let nextRun: Date;
  if (nextMin >= 24 * 60) {
    nextRun = new Date(midnight.getTime() + 24 * 60 * 60000 + offsetMin * 60000);
  } else {
    nextRun = new Date(midnight.getTime() + nextMin * 60000);
  }

  const diffSec = Math.floor((nextRun.getTime() - now.getTime()) / 1000);
  return Math.max(diffSec, 0);
}

/**
 * Formats seconds into MM:SS or HH:MM:SS.
 */
export function formatCountdown(totalSeconds: number): string {
  const h = Math.floor(totalSeconds / 3600);
  const m = Math.floor((totalSeconds % 3600) / 60);
  const s = totalSeconds % 60;
  if (h > 0) {
    return `${h}h ${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
  }
  return `${String(m).padStart(2, '0')}m ${String(s).padStart(2, '0')}s`;
}

/**
 * Counter widget placed at the top-left replacing the static logo.
 * Displays live countdown to the next scheduled fleet maintenance prediction cycle.
 */
export function MaintenanceCountdown() {
  const [secondsLeft, setSecondsLeft] = useState<number>(() => getSecondsUntilNextRun());

  useEffect(() => {
    const timer = setInterval(() => {
      setSecondsLeft(getSecondsUntilNextRun());
    }, 1000);

    return () => clearInterval(timer);
  }, []);

  const isRunning = secondsLeft === 0;

  return (
    <div
      className="absolute top-4 left-4 z-20 flex items-center gap-3 bg-slate-900/90 backdrop-blur-md px-4 py-2.5 rounded-xl border border-slate-700/80 shadow-lg pointer-events-auto select-none"
      title="Scheduled fleet predictive maintenance evaluation runs every 10 minutes at :02, :12, :22, :32, :42, :52"
    >
      {/* Animated status beacon */}
      <div className="relative flex items-center justify-center">
        <span
          className={`w-2.5 h-2.5 rounded-full ${
            isRunning ? 'bg-amber-400 animate-ping' : 'bg-emerald-400'
          }`}
        />
        <span
          className={`absolute w-2.5 h-2.5 rounded-full ${
            isRunning
              ? 'bg-amber-400 shadow-[0_0_10px_rgba(251,191,36,0.9)]'
              : 'bg-emerald-400 shadow-[0_0_8px_rgba(52,211,153,0.8)]'
          }`}
        />
      </div>

      {/* Countdown details */}
      <div className="flex flex-col">
        <div className="flex items-center gap-1.5">
          <span className="text-[10px] font-semibold text-slate-400 uppercase tracking-wider">
            Next Prediction
          </span>
          <span className="text-[10px] text-slate-500 font-mono">(10m)</span>
        </div>
        <div className="text-sm font-bold font-mono tracking-tight text-slate-100 flex items-center gap-1">
          {isRunning ? (
            <span className="text-amber-300 animate-pulse text-xs">Evaluating fleet...</span>
          ) : (
            <span>{formatCountdown(secondsLeft)}</span>
          )}
        </div>
      </div>
    </div>
  );
}
