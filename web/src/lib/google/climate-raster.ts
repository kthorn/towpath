import { CLIMATE_COLOR_LIMITS } from '../climate';
import type { ClimateGridSurface } from '../climate-grid';

type Coordinate = { lat: number; lon: number };
type Cell = { coordinate: Coordinate; value: number | null };
type Point = { x: number; y: number };
type Mask = { type: 'Polygon'; coordinates: number[][][] } | { type: 'MultiPolygon'; coordinates: number[][][][] };
type View = 'high_median' | 'high_p90' | 'low_median' | 'low_p10' | 'high_exceedance';
const LAT_KM = 111.195;
const BUCKET_DEGREES = 0.25;
const CUTOFF_KM = 15;

/** Normalized compact inverse-distance interpolation, never a sum of temperatures.
 * A missing nearest cell owns a transparent region, even beside valid samples.
 */
export function createClimateInterpolator(cells: readonly Cell[]): (point: Coordinate) => number | null {
  const buckets = new Map<string, Cell[]>();
  let south = Infinity, north = -Infinity, west = Infinity, east = -Infinity;
  for (const cell of cells) {
    south = Math.min(south, cell.coordinate.lat);
    north = Math.max(north, cell.coordinate.lat);
    west = Math.min(west, cell.coordinate.lon);
    east = Math.max(east, cell.coordinate.lon);
    const key = `${Math.floor(cell.coordinate.lon / BUCKET_DEGREES)}:${Math.floor(cell.coordinate.lat / BUCKET_DEGREES)}`;
    const bucket = buckets.get(key) ?? [];
    bucket.push(cell);
    buckets.set(key, bucket);
  }
  return ({ lat, lon }) => {
    const lonKm = LAT_KM * Math.cos(lat * Math.PI / 180);
    if (lat < south - CUTOFF_KM / LAT_KM || lat > north + CUTOFF_KM / LAT_KM
      || lon < west - CUTOFF_KM / lonKm || lon > east + CUTOFF_KM / lonKm) return null;
    const bx = Math.floor(lon / BUCKET_DEGREES);
    const by = Math.floor(lat / BUCKET_DEGREES);
    const xRadius = Math.ceil(CUTOFF_KM / Math.max(lonKm * BUCKET_DEGREES, 0.1));
    let nearest = Infinity;
    let nearestMissing = false;
    let total = 0;
    let weightSum = 0;
    for (let x = bx - xRadius; x <= bx + xRadius; x++) {
      for (let y = by - 1; y <= by + 1; y++) {
        for (const cell of buckets.get(`${x}:${y}`) ?? []) {
          const dx = (cell.coordinate.lon - lon) * lonKm;
          const dy = (cell.coordinate.lat - lat) * LAT_KM;
          const distance = Math.hypot(dx, dy);
          if (distance >= CUTOFF_KM) continue;
          const missing = cell.value === null || !Number.isFinite(cell.value);
          if (distance < 0.000001) return missing ? null : cell.value;
          if (distance < nearest || (distance === nearest && missing)) {
            nearest = distance;
            nearestMissing = missing;
          }
          if (missing) continue;
          const weight = ((1 - distance / CUTOFF_KM) / distance) ** 2;
          total += cell.value! * weight;
          weightSum += weight;
        }
      }
    }
    return nearestMissing || !weightSum ? null : total / weightSum;
  };
}

/** Fixed metric domains match the named-location legend; probabilities use 0–1. */
export function climateRasterColor(view: View, value: number): [number, number, number] {
  const limits = view === 'high_exceedance' ? { min: 0, max: 1 }
    : CLIMATE_COLOR_LIMITS[view.startsWith('low') ? 'low' : 'high'];
  const position = Math.min(1, Math.max(0, (value - limits.min) / (limits.max - limits.min)));
  // Same HSL scale as climateColor, converted directly for ImageData pixels.
  const hue = (220 - 220 * position) / 60;
  const chroma = (1 - Math.abs(2 * 0.75 - 1)) * 0.72;
  const x = chroma * (1 - Math.abs(hue % 2 - 1));
  const offset = 0.75 - chroma / 2;
  const rgb = hue < 1 ? [chroma, x, 0] : hue < 2 ? [x, chroma, 0]
    : hue < 3 ? [0, chroma, x] : [0, x, chroma];
  return rgb.map((channel) => Math.round((channel + offset) * 255)) as [number, number, number];
}

/** Limit interpolation work and memory independently of screen size and DPR. */
export function rasterDimensions(width: number, height: number, dpr = 1): { width: number; height: number } {
  const scale = Math.min(Math.max(1, Math.min(dpr, 2)), 384 / Math.max(width, height, 1));
  return { width: Math.max(1, Math.round(width * scale)), height: Math.max(1, Math.round(height * scale)) };
}

type ClipContext = Pick<CanvasRenderingContext2D, 'beginPath' | 'moveTo' | 'lineTo' | 'closePath' | 'clip'>;
export function traceLandMask(context: ClipContext, mask: Mask, project: (lon: number, lat: number) => Point | null): void {
  context.beginPath();
  const polygons = mask.type === 'Polygon' ? [mask.coordinates] : mask.coordinates;
  for (const polygon of polygons) {
    for (const ring of polygon) {
      const points = ring.map(([lon, lat]) => project(lon, lat));
      if (points.some((point) => !point) || !points.length) continue;
      points.forEach((point, index) => {
        if (index === 0) context.moveTo(point!.x, point!.y);
        else context.lineTo(point!.x, point!.y);
      });
      context.closePath();
    }
  }
  context.clip('evenodd');
}

interface LatLng { lat(): number; lng(): number }
interface Projection {
  fromLatLngToDivPixel(coordinate: LatLng | { lat: number; lng: number }): Point | null;
  fromDivPixelToLatLng(point: Point): LatLng | null;
}
export interface ClimateRasterMap {
  getDiv(): HTMLElement;
  getCenter(): LatLng | undefined;
}
interface Overlay {
  onAdd(): void;
  onRemove(): void;
  draw(): void;
  setMap(map: ClimateRasterMap | null): void;
  getPanes(): { overlayLayer: HTMLElement } | null;
  getProjection(): Projection;
}
export interface ClimateRasterMapsNamespace { OverlayView: new () => Overlay }
export interface ClimateRaster {
  setSurface(surface: ClimateGridSurface | null, opacity: number): void;
  destroy(): void;
}

/** OverlayView owns move/zoom redraws. No map click handlers or interactive pane. */
export function createClimateRaster(map: ClimateRasterMap, maps: ClimateRasterMapsNamespace): ClimateRaster {
  const documentRef = map.getDiv().ownerDocument;
  const windowRef = documentRef.defaultView!;
  const canvas = documentRef.createElement('canvas');
  canvas.className = 'pound-climate-raster';
  canvas.setAttribute('aria-hidden', 'true');
  Object.assign(canvas.style, { position: 'absolute', pointerEvents: 'none' });
  let surface: ClimateGridSurface | null = null;
  let interpolate: ReturnType<typeof createClimateInterpolator> | null = null;
  let destroyed = false;
  let attached = false;
  let pending: number | undefined;

  const paint = () => {
    pending = undefined;
    if (destroyed || !surface || !interpolate || !attached) return;
    const projection = overlay.getProjection();
    const center = map.getCenter();
    if (!projection || !center) return;
    const centerPixel = projection.fromLatLngToDivPixel(center);
    if (!centerPixel) return;
    const element = map.getDiv();
    const width = element.clientWidth;
    const height = element.clientHeight;
    if (!width || !height) return;
    const left = centerPixel.x - width / 2;
    const top = centerPixel.y - height / 2;
    const size = rasterDimensions(width, height, windowRef.devicePixelRatio);
    // Keep the geographic coastline crisp while bounding costly interpolation separately.
    const backingScale = Math.min(Math.max(1, Math.min(windowRef.devicePixelRatio || 1, 2)), 1536 / Math.max(width, height));
    canvas.width = Math.max(1, Math.round(width * backingScale));
    canvas.height = Math.max(1, Math.round(height * backingScale));
    Object.assign(canvas.style, { left: `${left}px`, top: `${top}px`, width: `${width}px`, height: `${height}px` });
    const context = canvas.getContext('2d');
    if (!context) return;
    const image = context.createImageData(size.width, size.height);
    for (let y = 0; y < size.height; y++) {
      for (let x = 0; x < size.width; x++) {
        const coordinate = projection.fromDivPixelToLatLng({
          x: left + (x + 0.5) * width / size.width,
          y: top + (y + 0.5) * height / size.height,
        });
        if (!coordinate) continue;
        const value = interpolate({ lat: coordinate.lat(), lon: coordinate.lng() });
        if (value === null) continue;
        const offset = (y * size.width + x) * 4;
        const color = climateRasterColor(surface.view, value);
        image.data.set([...color, 255], offset);
      }
    }
    // putImageData ignores clipping; paint to an offscreen source, then drawImage.
    const source = documentRef.createElement('canvas');
    source.width = size.width;
    source.height = size.height;
    source.getContext('2d')?.putImageData(image, 0, 0);
    context.save();
    traceLandMask(context, surface.mask, (lon, lat) => {
      const pixel = projection.fromLatLngToDivPixel({ lat, lng: lon });
      return pixel ? { x: (pixel.x - left) * canvas.width / width, y: (pixel.y - top) * canvas.height / height } : null;
    });
    context.drawImage(source, 0, 0, canvas.width, canvas.height);
    context.restore();
  };
  const schedule = () => {
    if (destroyed || pending !== undefined) return;
    pending = windowRef.requestAnimationFrame(paint);
  };
  const cancel = () => {
    if (pending !== undefined) windowRef.cancelAnimationFrame(pending);
    pending = undefined;
  };
  const overlay = new maps.OverlayView();
  overlay.onAdd = () => { overlay.getPanes()?.overlayLayer.append(canvas); schedule(); };
  overlay.draw = schedule;
  overlay.onRemove = () => { cancel(); canvas.remove(); };
  return {
    setSurface(next, opacity) {
      if (destroyed) return;
      const changed = surface !== next;
      surface = next;
      if (changed) interpolate = next ? createClimateInterpolator(next.cells) : null;
      canvas.style.opacity = String(Number.isFinite(opacity) ? Math.min(1, Math.max(0, opacity)) : 0);
      if (!next) {
        cancel();
        if (attached) overlay.setMap(null);
        attached = false;
        canvas.remove();
      } else {
        if (!attached) { attached = true; overlay.setMap(map); }
        if (changed) schedule();
      }
    },
    destroy() {
      destroyed = true;
      cancel();
      if (attached) overlay.setMap(null);
      attached = false;
      surface = null;
      interpolate = null;
      canvas.remove();
    },
  };
}
