import type { LatLon } from './types';

export const TRANSFER_MODES = ['WALK', 'DRIVE', 'TRANSIT', 'BICYCLE'] as const;
export type TransferMode = (typeof TRANSFER_MODES)[number];

export interface GoogleLatLng {
  lat: number;
  lng: number;
}

function transferMode(value: string | undefined): TransferMode {
  return TRANSFER_MODES.includes(value as TransferMode) ? (value as TransferMode) : 'WALK';
}

export const config = {
  googleMapsApiKey: import.meta.env.VITE_GOOGLE_MAPS_API_KEY ?? '',
  transferMode: transferMode(import.meta.env.VITE_TRANSFER_MODE),
};

export function toGoogleLatLng(coordinate: LatLon): GoogleLatLng {
  return { lat: coordinate.lat, lng: coordinate.lon };
}
