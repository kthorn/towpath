<script lang="ts">
  import type { BoatSettings, BoatSettingsStore, SettingsSaveResult } from '../lib/stores/boat-settings';

  let { store, onSave, onCancel }: {
    store: BoatSettingsStore;
    onSave(result: SettingsSaveResult): void;
    onCancel(): void;
  } = $props();

  let length = $state<string | number>($store.boat_length_m ?? '');
  let beam = $state<string | number>($store.boat_beam_m ?? '');
  let draft = $state<string | number>($store.boat_draft_m ?? '');
  let height = $state<string | number>($store.boat_height_m ?? '');
  let bridgeDelay = $state<string | number>($store.movable_bridge_delay_min ?? '');
  let errors = $state<Partial<Record<keyof BoatSettings, string>>>({});

  let lengthInput: HTMLInputElement;
  let beamInput: HTMLInputElement;
  let draftInput: HTMLInputElement;
  let heightInput: HTMLInputElement;
  let bridgeDelayInput: HTMLInputElement;

  function parseDraft(value: string | number, label: string): number | null {
    if (String(value).trim() === '') return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed <= 0) throw new Error(`${label} must be greater than 0.`);
    return parsed;
  }

  function parseBridgeDelay(value: string | number): number | null {
    if (String(value).trim() === '') return null;
    const parsed = Number(value);
    if (!Number.isFinite(parsed) || parsed < 0) throw new Error('Movable-bridge delay must be zero or greater.');
    return parsed;
  }

  function submit() {
    const nextErrors: Partial<Record<keyof BoatSettings, string>> = {};
    let parsedLength: number | null = null;
    let parsedBeam: number | null = null;
    let parsedDraft: number | null = null;
    let parsedHeight: number | null = null;
    let parsedBridgeDelay: number | null = null;

    try { parsedLength = parseDraft(length, 'Boat length'); } catch (cause) { nextErrors.boat_length_m = cause instanceof Error ? cause.message : String(cause); }
    try { parsedBeam = parseDraft(beam, 'Boat beam'); } catch (cause) { nextErrors.boat_beam_m = cause instanceof Error ? cause.message : String(cause); }
    try { parsedDraft = parseDraft(draft, 'Boat draft'); } catch (cause) { nextErrors.boat_draft_m = cause instanceof Error ? cause.message : String(cause); }
    try { parsedHeight = parseDraft(height, 'Boat height'); } catch (cause) { nextErrors.boat_height_m = cause instanceof Error ? cause.message : String(cause); }
    try { parsedBridgeDelay = parseBridgeDelay(bridgeDelay); } catch (cause) { nextErrors.movable_bridge_delay_min = cause instanceof Error ? cause.message : String(cause); }

    errors = nextErrors;
    if (Object.keys(nextErrors).length > 0) {
      const firstInvalid = nextErrors.boat_length_m ? lengthInput
        : nextErrors.boat_beam_m ? beamInput
        : nextErrors.boat_draft_m ? draftInput
        : nextErrors.boat_height_m ? heightInput
        : bridgeDelayInput;
      firstInvalid?.focus();
      return;
    }

    const result = store.save({
      boat_length_m: parsedLength,
      boat_beam_m: parsedBeam,
      boat_draft_m: parsedDraft,
      boat_height_m: parsedHeight,
      movable_bridge_delay_min: parsedBridgeDelay,
    });
    onSave(result);
  }
</script>

<form class="settings-card" novalidate onsubmit={(event) => { event.preventDefault(); submit(); }}>
  <p>These optional dimensions are saved in this browser and applied to every route.</p>
  <div class="constraint-grid">
    <label for="boat-length">Boat length (m)</label>
    <input id="boat-length" type="number" min="0.1" step="0.1" bind:value={length} bind:this={lengthInput}
      aria-invalid={errors.boat_length_m ? 'true' : undefined}
      aria-describedby={errors.boat_length_m ? 'boat-length-error' : undefined} />

    <label for="boat-beam">Boat beam (m)</label>
    <input id="boat-beam" type="number" min="0.1" step="0.1" bind:value={beam} bind:this={beamInput}
      aria-invalid={errors.boat_beam_m ? 'true' : undefined}
      aria-describedby={errors.boat_beam_m ? 'boat-beam-error' : undefined} />

    <label for="boat-draft">Boat draft (m)</label>
    <input id="boat-draft" type="number" min="0.1" step="0.1" bind:value={draft} bind:this={draftInput}
      aria-invalid={errors.boat_draft_m ? 'true' : undefined}
      aria-describedby={errors.boat_draft_m ? 'boat-draft-error' : undefined} />

    <label for="boat-height">Boat height (m)</label>
    <input id="boat-height" type="number" min="0.1" step="0.1" bind:value={height} bind:this={heightInput}
      aria-invalid={errors.boat_height_m ? 'true' : undefined}
      aria-describedby={errors.boat_height_m ? 'boat-height-error' : undefined} />

    <label for="movable-bridge-delay">Movable-bridge delay (min; blank uses route default)</label>
    <input id="movable-bridge-delay" type="number" min="0" step="0.5"
      bind:value={bridgeDelay} bind:this={bridgeDelayInput}
      aria-invalid={errors.movable_bridge_delay_min ? 'true' : undefined}
      aria-describedby={errors.movable_bridge_delay_min ? 'movable-bridge-delay-error' : undefined} />
  </div>
  {#if Object.keys(errors).length > 0}
    <div role="alert">
      {#if errors.boat_length_m}<span id="boat-length-error">{errors.boat_length_m}</span>{/if}
      {#if errors.boat_beam_m}<span id="boat-beam-error">{errors.boat_beam_m}</span>{/if}
      {#if errors.boat_draft_m}<span id="boat-draft-error">{errors.boat_draft_m}</span>{/if}
      {#if errors.boat_height_m}<span id="boat-height-error">{errors.boat_height_m}</span>{/if}
      {#if errors.movable_bridge_delay_min}<span id="movable-bridge-delay-error">{errors.movable_bridge_delay_min}</span>{/if}
    </div>
  {/if}
  <button type="submit">Save settings</button>
  <button type="button" onclick={onCancel}>Cancel</button>
</form>
