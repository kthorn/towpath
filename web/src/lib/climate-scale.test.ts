import { describe, expect, it } from 'vitest';
import { resolveClimateScale, validClimateScale, zoomClimateScale } from './climate-scale';

describe('climate colour scale', () => {
  it('uses the nationwide 99.9th percentile, excluding missing values', () => {
    const cells = [...Array.from({length: 999}, () => ({value: 0.02})), {value: 0.8}, {value: null}];
    expect(resolveClimateScale('high_exceedance', cells)).toEqual({min: 0, max: 0.02});
  });
  it('retains isolated hot cells and supplies a nondegenerate all-zero range', () => {
    expect(resolveClimateScale('high_exceedance', [...Array.from({length: 3000}, () => ({value: 0})), {value: 1 / 175}]).max).toBe(1 / 175);
    expect(resolveClimateScale('high_exceedance', [{value: 0}, {value: null}])).toEqual({min: 0, max: 0.01});
  });
  it('honours both manual bounds and clips zooming to the metric domain', () => {
    expect(resolveClimateScale('high_exceedance', [], {min: 0.01, max: 0.05})).toEqual({min: 0.01, max: 0.05});
    expect(zoomClimateScale('high_exceedance', {min: 0, max: 0.04}, 0.5)).toEqual({min: 0.01, max: 0.03});
    expect(zoomClimateScale('high_exceedance', {min: 0, max: 1}, 2)).toEqual({min: 0, max: 1});
    expect(validClimateScale('high_exceedance', {min: 0.2, max: 0.1})).toBe(false);
    expect(validClimateScale('high_exceedance', {min: 0, max: 2})).toBe(false);
    expect(validClimateScale('high_p90', {min: NaN, max: 30})).toBe(false);
  });
});
