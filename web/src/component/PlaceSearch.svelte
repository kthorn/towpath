<script lang="ts">
  import { onMount } from 'svelte';
  import type { PlaceSearch, SelectedPlace } from '../lib/google/contracts';

  let { label, search, onselect }: { label: string; search: PlaceSearch; onselect: (place: SelectedPlace) => void } = $props();
  let container: HTMLElement;
  let error = $state('');
  onMount(() => search.attach(container, (place) => {
    error = '';
    onselect(place);
  }, (cause) => {
    error = cause instanceof Error ? cause.message : String(cause);
  }));
</script>

<div class="place-search-field">
  <span class="place-search-label" aria-hidden="true">{label}</span>
  <span class="place-search-host" bind:this={container} aria-label={label}></span>
</div>
{#if error}<p role="alert">Place search unavailable: {error}. Use coordinates below.</p>{/if}
