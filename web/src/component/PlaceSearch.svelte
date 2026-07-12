<script lang="ts">
  import { onMount } from 'svelte';
  import type { PlaceSearch, SelectedPlace } from '../lib/google/contracts';

  let { label, search, onselect }: { label: string; search: PlaceSearch; onselect: (place: SelectedPlace) => void } = $props();
  let input: HTMLInputElement;
  let error = $state('');
  onMount(() => search.attach(input, onselect, (cause) => {
    error = cause instanceof Error ? cause.message : String(cause);
  }));
</script>

<label>{label}<input bind:this={input} type="search" autocomplete="off" placeholder="Search for a place" /></label>
{#if error}<p role="alert">Place search unavailable: {error}. Use coordinates below.</p>{/if}
