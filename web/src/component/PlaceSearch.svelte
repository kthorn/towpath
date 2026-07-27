<script lang="ts">
  import { onMount } from 'svelte';
  import type { PlaceSearch, SelectedPlace } from '../lib/google/contracts';

  let { label, search, onselect }: { label: string; search: PlaceSearch; onselect: (place: SelectedPlace) => void } = $props();
  let container: HTMLElement;
  let error = $state('');
  const handleSelect = (place: SelectedPlace) => {
    error = '';
    onselect(place);
  };
  const handleUnavailable = (cause: unknown) => {
    error = cause instanceof Error ? cause.message : String(cause);
  };
  onMount(() => search.attach(container, handleSelect, handleUnavailable));
</script>

<div class="place-search-field">
  <span class="place-search-label" aria-hidden="true">{label}</span>
  <span class="place-search-host" bind:this={container} aria-label={label}></span>
</div>
{#if error}<p role="alert">Place search unavailable: {error}. Use coordinates below.</p>{/if}
