<script lang="ts">
  import type { BoatSettingsStore } from '../lib/stores/boat-settings';
  let { store }: { store: BoatSettingsStore } = $props();
  let length = $state<string | number>($store.boat_length_m ?? '');
  let beam = $state<string | number>($store.boat_beam_m ?? '');
  let draft = $state<string | number>($store.boat_draft_m ?? '');
  let height = $state<string | number>($store.boat_height_m ?? '');
  let error = $state('');
  let saved = $state(false);
  function positiveOptional(label: string, value: string | number): number | null {
    if (String(value).trim() === '') return null;
    const number = Number(value);
    if (!Number.isFinite(number) || number <= 0) throw new Error(`${label} must be greater than 0.`);
    return number;
  }
  function submit() {
    error = ''; saved = false;
    try {
      store.save({ boat_length_m: positiveOptional('Boat length', length), boat_beam_m: positiveOptional('Boat beam', beam), boat_draft_m: positiveOptional('Boat draft', draft), boat_height_m: positiveOptional('Boat height', height) });
      saved = true;
    } catch (cause) { error = cause instanceof Error ? cause.message : String(cause); }
  }
</script>

<form class="settings-card" novalidate onsubmit={(event) => { event.preventDefault(); submit(); }}>
  <h1>Boat settings</h1>
  <p>These optional dimensions are saved in this browser and applied to every route.</p>
  <div class="constraint-grid">
    <label>Boat length (m)<input type="number" min="0.1" step="0.1" bind:value={length} /></label>
    <label>Boat beam (m)<input type="number" min="0.1" step="0.1" bind:value={beam} /></label>
    <label>Boat draft (m)<input type="number" min="0.1" step="0.1" bind:value={draft} /></label>
    <label>Boat height (m)<input type="number" min="0.1" step="0.1" bind:value={height} /></label>
  </div>
  <button type="submit">Save settings</button>
  {#if error}<p role="alert">{error}</p>{/if}
  {#if saved}<p role="status" class="save-status">Settings saved.</p>{/if}
</form>
