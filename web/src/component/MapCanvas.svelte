<script lang="ts">
  import { onMount } from 'svelte';
  import type { MapView } from '../lib/google/contracts';
  let { load, onclick, onready }: { load: (element: HTMLElement) => Promise<MapView>; onclick: (coordinate: { lat: number; lon: number }) => void; onready: (view: MapView | undefined) => void } = $props();
  let element: HTMLElement; let error = $state('');
  onMount(() => {
    let view: MapView | undefined; let removeClick: (() => void) | undefined; let disposed = false;
    load(element).then((loaded) => { if (disposed) { loaded.destroy(); return; } view = loaded; removeClick = view.onMapClick(onclick); onready(view); }).catch((cause) => { if (disposed) return; error = cause instanceof Error ? cause.message : String(cause); onready(undefined); });
    return () => { disposed = true; removeClick?.(); view?.destroy(); onready(undefined); };
  });
</script>

<section class="map-shell" aria-label="Journey map" aria-describedby="map-help"><span id="map-help" style="position:absolute;width:1px;height:1px;overflow:hidden;clip:rect(0,0,0,0)">Interactive map for selecting trip endpoints and viewing land and canal routes.</span><div class="map" data-testid="journey-map-canvas" bind:this={element}></div>{#if error}<p role="status" class="map-error">Map unavailable: {error}. Candidate lists and route planning remain available.</p>{/if}</section>
