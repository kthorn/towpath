import { describe, expect, it } from 'vitest';

import { parseSchedule } from './schedule';

describe('parseSchedule', () => {
  it('parses a complete schedule', () => {
    expect(parseSchedule(7, 6)).toEqual({ days: 7, hours_per_day: 6 });
  });

  it('requires days from one through 365', () => {
    expect(() => parseSchedule('', 6)).toThrow('Days must be a whole number from 1 through 365.');
  });

  it('requires hours per day from more than zero through 24', () => {
    expect(() => parseSchedule(7, 25)).toThrow('Hours per day must be greater than 0 and at most 24.');
  });
});
