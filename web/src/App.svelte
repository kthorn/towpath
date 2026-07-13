<script lang="ts">
  import { onMount, tick } from 'svelte';
  import './app.css';
  import BoatConstraints from './component/BoatConstraints.svelte';
  import BoatSettings from './component/BoatSettings.svelte';
  import EndpointPanel from './component/EndpointPanel.svelte';
  import MapCanvas from './component/MapCanvas.svelte';
  import TripSummary from './component/TripSummary.svelte';
  import type { AppDependencies } from './lib/app';
  import type { EndpointSlot } from './lib/google/contracts';
  import { createNavigation, type AppRoute } from './lib/navigation';
  import { createBoatSettingsStore } from './lib/stores/boat-settings';

  let { dependencies }: { dependencies: AppDependencies } = $props();
  const store = $derived(dependencies.store);
  const boatSettings = createBoatSettingsStore();
  let active = $state<EndpointSlot>('origin');
  let plannerSession = $state({ days: '' as string | number, hours: '6' as string | number, derelict: false });

  const navigation = createNavigation();
  let plannerHeading: HTMLHeadingElement;
  let settingsHeading: HTMLHeadingElement;

  onMount(() => {
    let firstPublication = true;
    const unsubscribe = navigation.subscribe((route: AppRoute) => {
      if (firstPublication) {
        firstPublication = false;
        return;
      }
      void tick().then(() => (route === 'planner' ? plannerHeading : settingsHeading)?.focus());
    });
    return () => { unsubscribe(); navigation.destroy(); };
  });

  function handleNavClick(event: MouseEvent, route: AppRoute, ordinaryAction: () => void = () => navigation.navigate(route)) {
    if (!(event.currentTarget instanceof HTMLAnchorElement)) return;
    if (event.button !== 0) return;
    if (event.metaKey || event.altKey || event.ctrlKey || event.shiftKey) return;
    if (event.defaultPrevented) return;
    if (event.currentTarget.hasAttribute('download')) return;
    const target = event.currentTarget.target;
    if (target && target !== '_self') return;
    event.preventDefault();
    ordinaryAction();
  }
</script>

<header><div><span class="wordmark">Pound</span><p>Canal journey planner</p><nav aria-label="Primary"><a href="/" aria-current={$navigation === 'planner' ? 'page' : undefined} onclick={(event) => handleNavClick(event, 'planner')}>Plan trip</a><a href="/settings" aria-current={$navigation === 'settings' ? 'page' : undefined} onclick={(event) => handleNavClick(event, 'settings')}>Settings</a></nav></div></header>
{#if $navigation === 'planner'}
  <main class="planner-page">
    <h1 bind:this={plannerHeading} tabindex="-1">Plan your canal journey</h1>
    <div class="map-column">
      <fieldset class="map-target"><legend>Map click sets</legend><label><input type="radio" bind:group={active} value="origin" /> Set origin from map</label><label><input type="radio" bind:group={active} value="destination" /> Set destination from map</label></fieldset>
      <MapCanvas load={dependencies.loadMapView} onclick={(coordinate) => dependencies.store.setEndpointCoordinate(active, coordinate)} onready={(view) => dependencies.store.setMapView(view)} />
    </div>
    <div class="planner-column">
      <EndpointPanel slot="origin" endpoint={$store.origin} {store} search={dependencies.placeSearch} />
      <EndpointPanel slot="destination" endpoint={$store.destination} {store} search={dependencies.placeSearch} />
      <BoatConstraints {store} settings={boatSettings} bind:days={plannerSession.days} bind:hours={plannerSession.hours} bind:derelict={plannerSession.derelict} />
      <TripSummary state={$store} />
    </div>
  </main>
{:else}
  <main class="settings-page">
    <h1 bind:this={settingsHeading} tabindex="-1">Boat settings</h1>
    <BoatSettings store={boatSettings} />
  </main>
{/if}
<footer>
  Canal routes are planning guidance; verify navigation restrictions and safe access locally.
  Map data © Google and
  <a href="https://www.openstreetmap.org/copyright" target="_blank" rel="noopener noreferrer">© OpenStreetMap contributors</a>.
</footer>
