<script lang="ts">
  import type { EndpointSlot } from '../lib/google/contracts';
  import type { EndpointState, TripStore } from '../lib/stores/trip';
  let { slot, endpoint, store }: { slot: EndpointSlot; endpoint: EndpointState; store: TripStore } = $props();
  const km = (metres: number) => `${(metres / 1000).toFixed(2)} km`;
  const reason = (value: string) => value.toLowerCase().replaceAll('_', ' ');
</script>

<div class="candidate-list">
  {#if endpoint.loading}<p role="status">Finding canal access points…</p>{/if}
  {#if endpoint.error}<p role="alert">{endpoint.error}</p>{/if}
  {#if !endpoint.loading && !endpoint.error && endpoint.candidates.length === 0}<p>No candidates loaded yet.</p>{/if}
  {#each endpoint.candidates as item}
    <label class="candidate">
      <input type="radio" name={`${slot}-candidate`} value={item.candidate.uid} checked={endpoint.selectedUid === item.candidate.uid} onchange={() => store.selectCandidate(slot, item.candidate.uid)} />
      <span><strong>{item.candidate.display_name}</strong>{#if item.recommended}<em>Recommended</em>{/if}</span>
      <small>{km(item.candidate.straight_line_distance_m)} straight line</small>
      {#if item.available}<small>{Math.round(item.durationSeconds / 60)} min · {km(item.distanceMeters)} transfer</small>{:else}<small>Unavailable: {reason(item.reason)}</small>{/if}
    </label>
  {/each}
</div>
