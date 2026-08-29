export function parseSchedule(days: string | number, hours: string | number): {
  days: number;
  hours_per_day: number;
} {
  const dayCount = Number(days);
  if (!Number.isInteger(dayCount) || dayCount < 1 || dayCount > 365) {
    throw new Error('Days must be a whole number from 1 through 365.');
  }
  const hoursPerDay = Number(hours);
  if (!Number.isFinite(hoursPerDay) || hoursPerDay <= 0 || hoursPerDay > 24) {
    throw new Error('Hours per day must be greater than 0 and at most 24.');
  }
  return { days: dayCount, hours_per_day: hoursPerDay };
}
