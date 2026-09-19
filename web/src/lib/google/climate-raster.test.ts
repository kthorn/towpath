import { describe, expect, it, vi } from 'vitest';
import { createClimateInterpolator, climateRasterColor, rasterDimensions, traceLandMask } from './climate-raster';

const cell = (lon: number, value: number | null, lat = 55) => ({ id: String(lon), coordinate: { lat, lon }, value, n_days: 175 });

describe('climate raster interpolation', () => {
  it('recovers samples exactly and averages temperature rather than accumulating intensity', () => {
    const interpolate = createClimateInterpolator([cell(-0.1, 10), cell(0.1, 30)]);
    expect(interpolate({ lat: 55, lon: -0.1 })).toBe(10);
    expect(interpolate({ lat: 55, lon: 0 })).toBeCloseTo(20);
    expect(createClimateInterpolator([cell(-0.1, 20), cell(0.1, 20)])({ lat: 55, lon: 0 })).toBeCloseTo(20);
  });
  it('keeps missing cells and distant extrapolation transparent', () => {
    const interpolate = createClimateInterpolator([cell(-0.1, 20), cell(0, null), cell(0.1, 25)]);
    expect(interpolate({ lat: 55, lon: 0 })).toBeNull();
    expect(interpolate({ lat: 55, lon: 0.02 })).toBeNull();
    expect(interpolate({ lat: 56, lon: 0 })).toBeNull();
  });
  it('uses geographical rather than pixel distance and preserves probability zero', () => {
    const interpolate = createClimateInterpolator([cell(0, 0)]);
    expect(interpolate({ lat: 55, lon: 0 })).toBe(0);
    expect(interpolate({ lat: 55.1, lon: 0 })).toBe(0);
    expect(interpolate({ lat: 55.2, lon: 0 })).toBeNull();
  });
  it('uses fixed color limits and bounds backing resolution even at large DPR', () => {
    expect(climateRasterColor('high_p90', 35)).toEqual(climateRasterColor('high_p90', 100));
    expect(climateRasterColor('high_exceedance', 0)).not.toEqual(climateRasterColor('high_exceedance', 1));
    expect(rasterDimensions(2000, 1000, 4)).toEqual({ width: 384, height: 192 });
  });
  it('traces separate rings for holes and islands with even-odd clipping', () => {
    const context = { beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), clip: vi.fn() };
    traceLandMask(context, { type: 'MultiPolygon', coordinates: [
      [[[0, 0], [3, 0], [3, 3], [0, 0]], [[1, 1], [2, 1], [1, 2], [1, 1]]],
      [[[4, 4], [5, 4], [4, 5], [4, 4]]],
    ] }, (lon, lat) => ({ x: lon, y: lat }));
    expect(context.moveTo).toHaveBeenCalledTimes(3);
    expect(context.closePath).toHaveBeenCalledTimes(3);
    expect(context.clip).toHaveBeenCalledWith('evenodd');
  });
});

import { createClimateRaster } from './climate-raster';
import type { ClimateGridSurface } from '../climate-grid';

it('attaches only when enabled, coalesces draws and removes pending work on detach/destroy', () => {
  vi.useFakeTimers();
  const pane = document.createElement('div');
  const element = document.createElement('div');
  const callbacks = new Map<number, FrameRequestCallback>();
  let token = 0;
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => { callbacks.set(++token, callback); return token; });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation((id) => { callbacks.delete(id); });
  class Overlay {
    static current: Overlay;
    onAdd = () => {};
    onRemove = () => {};
    draw = () => {};
    constructor() { Overlay.current = this; }
    setMap = vi.fn((map) => { if (map) this.onAdd(); else this.onRemove(); });
    getPanes() { return { overlayLayer: pane }; }
    getProjection() { return { fromLatLngToDivPixel: () => ({ x: 0, y: 0 }), fromDivPixelToLatLng: () => null }; }
  }
  const raster = createClimateRaster({ getDiv: () => element, getCenter: () => undefined }, { OverlayView: Overlay });
  const surface = { cells: [cell(0, 20)], view: 'high_p90', mask: { type: 'Polygon', coordinates: [] } } as unknown as ClimateGridSurface;
  expect(Overlay.current.setMap).not.toHaveBeenCalled();
  raster.setSurface(surface, 0.4);
  expect(pane.querySelector('canvas')?.style.pointerEvents).toBe('none');
  expect(pane.querySelector('canvas')?.style.opacity).toBe('0.4');
  Overlay.current.draw();
  Overlay.current.draw();
  expect(callbacks.size).toBe(0);
  vi.advanceTimersByTime(200);
  expect(callbacks.size).toBe(1);
  raster.setSurface(surface, 0.7);
  expect(pane.querySelector('canvas')?.style.opacity).toBe('0.7');
  raster.setSurface(null, 0.7);
  expect(pane.children).toHaveLength(0);
  expect(callbacks.size).toBe(0);
  raster.setSurface(surface, 0.4);
  expect(pane.children).toHaveLength(1);
  raster.destroy();
  raster.destroy();
  raster.setSurface(surface, 0.4);
  expect(pane.children).toHaveLength(0);
  expect(callbacks.size).toBe(0);
  vi.useRealTimers();
  vi.restoreAllMocks();
});

it('renders normalized pixel colors through a high-resolution coastline clip', () => {
  const element = document.createElement('div');
  Object.defineProperties(element, { clientWidth: { value: 8 }, clientHeight: { value: 8 } });
  const pane = document.createElement('div');
  const context = {
    createImageData: (width: number, height: number) => ({ data: new Uint8ClampedArray(width * height * 4) }),
    putImageData: vi.fn(), save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(),
    moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), clip: vi.fn(), drawImage: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  let scheduled: FrameRequestCallback | undefined;
  vi.spyOn(window, 'requestAnimationFrame').mockImplementation((callback) => { scheduled = callback; return 1; });
  vi.spyOn(window, 'cancelAnimationFrame').mockImplementation(() => {});
  class Overlay {
    onAdd = () => {};
    onRemove = () => {};
    draw = () => {};
    setMap(map: unknown) { if (map) this.onAdd(); else this.onRemove(); }
    getPanes() { return { overlayLayer: pane }; }
    getProjection() {
      return {
        fromLatLngToDivPixel: () => ({ x: 0, y: 0 }),
        fromDivPixelToLatLng: (point: { x: number; y: number }) => ({ lat: () => 55 - point.y / 100, lng: () => point.x / 100 }),
      };
    }
  }
  const raster = createClimateRaster({ getDiv: () => element, getCenter: () => ({ lat: () => 55, lng: () => 0 }) }, { OverlayView: Overlay });
  raster.setSurface({ cells: [cell(0, 0)], view: 'high_exceedance', mask: { type: 'Polygon', coordinates: [[[0, 54], [1, 54], [0, 55], [0, 54]]] } } as unknown as ClimateGridSurface, 0.4);
  scheduled?.(0);
  scheduled?.(0);
  expect(context.putImageData).toHaveBeenCalledOnce();
  const image = context.putImageData.mock.calls[0][0];
  expect(Array.from(image.data.slice(0, 4))).toEqual([...climateRasterColor('high_exceedance', 0), 255]);
  expect(context.clip).toHaveBeenCalledWith('evenodd');
  expect(context.drawImage).toHaveBeenCalledTimes(2);
  expect(context.clip.mock.invocationCallOrder[0]).toBeLessThan(context.drawImage.mock.invocationCallOrder[0]);
  raster.destroy();
  vi.restoreAllMocks();
});

it('gives rare exceedances visible contrast without changing temperature colours', () => {
  const zero = climateRasterColor('high_exceedance', 0);
  const rare = climateRasterColor('high_exceedance', 1 / 175, { min: 0, max: 0.02 });
  expect(Math.max(...rare.map((v, i) => Math.abs(v - zero[i])))).toBeGreaterThan(30);
  expect(climateRasterColor('high_exceedance', 0.01, { min: 0, max: 0.02 })).toEqual(climateRasterColor('high_p90', 17.5));
});

it('repositions the painted image during zoom and only resamples after movement settles', () => {
  vi.useFakeTimers();
  const element = document.createElement('div');
  Object.defineProperties(element, { clientWidth: { value: 8 }, clientHeight: { value: 8 } });
  const pane = document.createElement('div');
  const context = {
    createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4) }),
    putImageData: vi.fn(), save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(),
    moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), clip: vi.fn(), drawImage: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  let zoom = 1;
  const unproject = vi.fn(({ x, y }: { x: number; y: number }) => {
    const lat = 55 - y / (100 * zoom), lng = x / (100 * zoom);
    return { lat: () => lat, lng: () => lng };
  });
  class Overlay {
    static current: Overlay;
    constructor() { Overlay.current = this; }
    onAdd = () => {}; onRemove = () => {}; draw = () => {};
    setMap(map: unknown) { if (map) this.onAdd(); else this.onRemove(); }
    getPanes() { return { overlayLayer: pane }; }
    getProjection() { return {
      fromDivPixelToLatLng: unproject,
      fromLatLngToDivPixel: (ll: { lat: number | (() => number); lng: number | (() => number) }) => ({
        x: (typeof ll.lng === 'function' ? ll.lng() : ll.lng) * 100 * zoom,
        y: (55 - (typeof ll.lat === 'function' ? ll.lat() : ll.lat)) * 100 * zoom,
      }),
    }; }
  }
  const raster = createClimateRaster({ getDiv: () => element, getCenter: () => ({ lat: () => 55, lng: () => 0 }) }, { OverlayView: Overlay });
  raster.setSurface({ cells: [cell(0, 20)], view: 'high_p90', mask: { type: 'Polygon', coordinates: [] } } as unknown as ClimateGridSurface, 0.4);
  vi.advanceTimersByTime(200);
  expect(context.putImageData).toHaveBeenCalledTimes(1);
  unproject.mockClear();
  zoom = 2;
  for (let i = 0; i < 20; i++) { Overlay.current.draw(); vi.advanceTimersByTime(16); }
  expect(unproject).not.toHaveBeenCalled();
  expect(context.putImageData).toHaveBeenCalledTimes(1);
  expect(pane.querySelector('canvas')!.style.width).toBe('16px');
  vi.advanceTimersByTime(200);
  expect(context.putImageData).toHaveBeenCalledTimes(2);
  Overlay.current.draw();
  raster.destroy();
  vi.advanceTimersByTime(500);
  expect(context.putImageData).toHaveBeenCalledTimes(2);
  expect(pane.children).toHaveLength(0);
  vi.useRealTimers(); vi.restoreAllMocks();
});


it('yields long raster work between frames and cancels an unfinished surface', () => {
  vi.useFakeTimers();
  const element = document.createElement('div');
  Object.defineProperties(element, { clientWidth: { value: 8 }, clientHeight: { value: 100 } });
  const pane = document.createElement('div');
  const context = {
    createImageData: (w: number, h: number) => ({ data: new Uint8ClampedArray(w * h * 4) }),
    putImageData: vi.fn(), save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(),
    moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), clip: vi.fn(), drawImage: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  let clock = 0;
  vi.spyOn(window.performance, 'now').mockImplementation(() => clock += 4);
  class Overlay {
    onAdd = () => {}; onRemove = () => {}; draw = () => {};
    setMap(map: unknown) { if (map) this.onAdd(); else this.onRemove(); }
    getPanes() { return { overlayLayer: pane }; }
    getProjection() { return {
      fromLatLngToDivPixel: () => ({x: 0, y: 0}),
      fromDivPixelToLatLng: () => ({lat: () => 55, lng: () => 0}),
    }; }
  }
  const raster = createClimateRaster({getDiv: () => element, getCenter: () => ({lat: () => 55, lng: () => 0})}, {OverlayView: Overlay});
  raster.setSurface({cells: [cell(0, 20)], view: 'high_p90', mask: {type: 'Polygon', coordinates: []}} as unknown as ClimateGridSurface, 0.4);
  vi.advanceTimersByTime(17);
  expect(context.putImageData).not.toHaveBeenCalled();
  raster.setSurface(null, 0.4);
  vi.advanceTimersByTime(2000);
  expect(context.putImageData).not.toHaveBeenCalled();
  raster.destroy();
  vi.useRealTimers(); vi.restoreAllMocks();
});

it('yields coastline projection and cancels it without publishing a partial image', () => {
  vi.useFakeTimers();
  const element = document.createElement('div');
  Object.defineProperties(element, {clientWidth: {value: 1}, clientHeight: {value: 1}});
  const pane = document.createElement('div');
  const context = {
    createImageData: () => ({data: new Uint8ClampedArray(4)}), putImageData: vi.fn(),
    save: vi.fn(), restore: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(), closePath: vi.fn(), clip: vi.fn(), drawImage: vi.fn(),
  };
  vi.spyOn(HTMLCanvasElement.prototype, 'getContext').mockReturnValue(context as unknown as CanvasRenderingContext2D);
  let clock = 0;
  vi.spyOn(window.performance, 'now').mockImplementation(() => clock += 4);
  class Overlay {
    onAdd = () => {}; onRemove = () => {}; draw = () => {};
    setMap(map: unknown) { if (map) this.onAdd(); else this.onRemove(); }
    getPanes() { return {overlayLayer: pane}; }
    getProjection() { return {fromLatLngToDivPixel: () => ({x: 0, y: 0}), fromDivPixelToLatLng: () => ({lat: () => 55, lng: () => 0})}; }
  }
  const raster = createClimateRaster({getDiv: () => element, getCenter: () => ({lat: () => 55, lng: () => 0})}, {OverlayView: Overlay});
  raster.setSurface({cells: [cell(0,20)], view: 'high_p90', mask: {type: 'Polygon', coordinates: [Array.from({length: 100}, (_,i) => [i / 100, 55])]}} as unknown as ClimateGridSurface, 0.4);
  vi.advanceTimersByTime(17);
  expect(context.clip).not.toHaveBeenCalled();
  expect(context.drawImage).not.toHaveBeenCalled();
  raster.destroy();
  vi.advanceTimersByTime(5000);
  expect(context.drawImage).not.toHaveBeenCalled();
  vi.useRealTimers(); vi.restoreAllMocks();
});
