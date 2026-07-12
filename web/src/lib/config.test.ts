import { describe, expect, it } from 'vitest';

import { config } from './config';

describe('browser configuration', () => {
  it('provides the official Advanced Marker development map id by default', () => {
    expect(config.googleMapId).toBe('DEMO_MAP_ID');
  });
});
