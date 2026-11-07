import L from 'leaflet';

/**
 * Standard wind park map marker (16px circle).
 */
export const dotIcon = L.divIcon({
  className: '!bg-transparent !border-none',
  html: `<div class="w-4 h-4 rounded-full bg-emerald-500 border-2 border-white shadow-md hover:scale-125 transition-transform duration-150 cursor-pointer"></div>`,
  iconSize: [16, 16],
  iconAnchor: [8, 8],
});

/**
 * Selected wind park map marker with active highlight ring.
 */
export const selectedIcon = L.divIcon({
  className: '!bg-transparent !border-none',
  html: `<div class="w-6 h-6 rounded-full bg-blue-500 border-2 border-white ring-4 ring-blue-400/50 shadow-lg cursor-pointer"></div>`,
  iconSize: [24, 24],
  iconAnchor: [12, 12],
});

/**
 * Marker cluster badge icon displaying child count.
 */
export function clusterIcon(cluster: { getChildCount: () => number }) {
  const count = cluster.getChildCount();
  return L.divIcon({
    className: '!bg-transparent !border-none',
    html: `<div class="flex items-center justify-center w-10 h-10 rounded-full bg-slate-900/95 text-emerald-400 border-2 border-emerald-500 font-bold text-sm shadow-xl hover:scale-110 transition-transform cursor-pointer">${count}</div>`,
    iconSize: [40, 40],
    iconAnchor: [20, 20],
  });
}
