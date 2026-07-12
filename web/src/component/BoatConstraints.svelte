<script lang="ts">
  import type { TripStore } from '../lib/stores/trip';
  let { store }: { store: TripStore } = $props();
  let days = $state<string | number>(''); let hours = $state<string | number>('6'); let length = $state<string | number>(''); let beam = $state<string | number>(''); let draft = $state<string | number>(''); let height = $state<string | number>(''); let derelict = $state(false); let error = $state('');
  const optional = (value: string | number) => String(value).trim() === '' ? null : Number(value);
  function positiveOptional(label: string, value: string | number): number | null {
    const number = optional(value);
    if (number !== null && (!Number.isFinite(number) || number <= 0)) throw new Error(`${label} must be greater than 0.`);
    return number;
  }
  async function submit() {
    error = '';
    try {
      const hoursPerDay = Number(hours);
      if (String(hours).trim() === '' || !Number.isFinite(hoursPerDay) || hoursPerDay <= 0) throw new Error('Hours per day must be greater than 0.');
      const dayCount = positiveOptional('Days', days);
      if (dayCount !== null && !Number.isInteger(dayCount)) throw new Error('Days must be a whole number greater than 0.');
      await store.planCanalRoute({ days: dayCount, hours_per_day: hoursPerDay, boat_length_m: positiveOptional('Boat length', length), boat_beam_m: positiveOptional('Boat beam', beam), boat_draft_m: positiveOptional('Boat draft', draft), boat_height_m: positiveOptional('Boat height', height), allow_derelict: derelict });
    }
    catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
  }
</script>

<form novalidate onsubmit={(event) => { event.preventDefault(); submit(); }}>
  <h2>Boat and schedule</h2>
  <div class="constraint-grid">
    <label>Days (optional)<input type="number" min="1" bind:value={days} /></label>
    <label>Hours per day<input type="number" required min="0.1" step="0.5" bind:value={hours} /></label>
    <label>Boat length (m)<input type="number" min="0" step="0.1" bind:value={length} /></label>
    <label>Boat beam (m)<input type="number" min="0" step="0.1" bind:value={beam} /></label>
    <label>Boat draft (m)<input type="number" min="0" step="0.1" bind:value={draft} /></label>
    <label>Boat height (m)<input type="number" min="0" step="0.1" bind:value={height} /></label>
  </div>
  <label class="check"><input type="checkbox" bind:checked={derelict} /> Allow derelict waterways</label>
  <button type="submit">Plan canal route</button>
  {#if error}<p role="alert">{error}</p>{/if}
</form>
