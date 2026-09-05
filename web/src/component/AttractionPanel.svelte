<script lang="ts">
	import { onMount } from 'svelte';
	import type { LandRoute, TransferResult } from '../lib/google/contracts';
	import type { PlaceChoice, PlaceController, PlaceState } from '../lib/places/controller';

	let {
		controller,
		onPreview,
		onClearPreview,
	}: {
		controller: PlaceController;
		onPreview?: (routes: { outward: LandRoute; return: LandRoute }) => void;
		onClearPreview?: () => void;
	} = $props();

	let placeState: PlaceState = $state({
		status: 'idle',
		options: [],
		selected: null,
		access: [],
		error: '',
	});
	let query: string = $state('');
	let confirmedCandidate: string | null = $state(null);
	let previewingCandidate: string | null = $state(null);
	let previewError: string = $state('');
	let manualLatitude: string = $state('');
	let manualLongitude: string = $state('');
	let manualError: string = $state('');
	let mounted = false;
	let previewGeneration = 0;
	let observedSelectionRef: string | null = null;
	let hasObservedSelection = false;
	let resetNotifiedForRef: string | null | undefined;

	const FALLBACK_STATUSES = new Set(['ambiguous', 'incomplete', 'not_found', 'unavailable', 'error']);

		onMount(() => {
			mounted = true;
			const unsubscribe = controller.subscribe((next) => {
				const nextSelectionRef = next.selected?.option_ref ?? null;
				placeState = next;
				if (!hasObservedSelection) {
					observedSelectionRef = nextSelectionRef;
					hasObservedSelection = true;
					return;
				}
				if (nextSelectionRef !== observedSelectionRef) {
				confirmedCandidate = null;
				invalidatePreview();
				if (resetNotifiedForRef !== observedSelectionRef) {
					resetNotifiedForRef = observedSelectionRef;
					onClearPreview?.();
				}
				resetNotifiedForRef = undefined;
			}
			observedSelectionRef = nextSelectionRef;
		});
		return () => {
			mounted = false;
			invalidatePreview();
			onClearPreview?.();
			unsubscribe();
		};
	});

	function invalidatePreview() {
		previewGeneration += 1;
		previewingCandidate = null;
	}

	function notifyPreviewReset() {
		invalidatePreview();
		resetNotifiedForRef = placeState.selected?.option_ref ?? null;
		onClearPreview?.();
	}

	function submitSearch() {
		const text = query.trim();
		if (!text) return;
		notifyPreviewReset();
		previewError = '';
		controller.search(text);
	}

	function searchGoogle() {
		notifyPreviewReset();
		previewError = '';
		controller.searchGoogle();
	}

	function selectManual() {
		if (!manualLatitude.trim()) {
			manualError = 'Latitude must be between -90 and 90.';
			return;
		}
		if (!manualLongitude.trim()) {
			manualError = 'Longitude must be between -180 and 180.';
			return;
		}
		const latitude = Number(manualLatitude.trim());
		const longitude = Number(manualLongitude.trim());
		if (!Number.isFinite(latitude) || latitude < -90 || latitude > 90) {
			manualError = 'Latitude must be between -90 and 90.';
			return;
		}
		if (!Number.isFinite(longitude) || longitude < -180 || longitude > 180) {
			manualError = 'Longitude must be between -180 and 180.';
			return;
		}
		manualError = '';
		notifyPreviewReset();
		controller.selectManual({ lat: latitude, lon: longitude });
	}

	function clearAttraction() {
		query = '';
		confirmedCandidate = null;
		previewError = '';
		notifyPreviewReset();
		controller.cancel();
	}

	function selectAttraction(optionRef: string) {
		notifyPreviewReset();
		controller.select(optionRef);
	}

	function toggleConfirmation(candidateId: string, event: Event) {
		const input = event.currentTarget;
		if (!(input instanceof HTMLInputElement)) return;
		confirmedCandidate = input.checked ? candidateId : null;
	}

	async function previewWalk(candidateId: string) {
		if (!onPreview || confirmedCandidate !== candidateId) return;
		previewError = '';
		previewingCandidate = candidateId;
		const requestGeneration = previewGeneration;
		try {
			const routes = await controller.walkingRoutes(candidateId, true);
			if (!mounted || requestGeneration !== previewGeneration) return;
			onPreview(routes);
		} catch (cause) {
			if (!mounted || requestGeneration !== previewGeneration) return;
			if (cause instanceof DOMException && cause.name === 'AbortError') return;
			previewError = cause instanceof Error ? cause.message : String(cause);
		} finally {
			previewingCandidate = null;
		}
	}

	function formatDuration(seconds: number): string {
		const minutes = Math.max(0, Math.round(seconds / 60));
		return `${minutes} minute${minutes === 1 ? '' : 's'}`;
	}

	function transferText(transfer: TransferResult): string {
		return transfer.available ? formatDuration(transfer.durationSeconds) : 'Unavailable';
	}

	function sourceLabel(source: PlaceChoice['source']): string {
		if (source === 'google') return 'Google Maps';
		if (source === 'manual') return 'Manual coordinates';
		return 'OpenStreetMap';
	}

	function choiceLabel(option: PlaceChoice): string {
		return option.address ? `${option.name}, ${option.address}` : option.name;
	}
</script>

<section class="attraction-panel" aria-labelledby="attraction-heading">
	<h2 id="attraction-heading">Visit an attraction</h2>
	<p class="intro">Find a named place, then review walking access from the canal.</p>

	<form class="attraction-search" onsubmit={(event) => { event.preventDefault(); submitSearch(); }}>
		<label for="attraction-query">Attraction name</label>
		<div class="search-actions">
			<input id="attraction-query" type="search" maxlength="200" bind:value={query} placeholder="e.g. Bletchley Park" />
			<button type="submit">Search</button>
		</div>
	</form>

	{#if placeState.status === 'pending'}
		<p class="status" role="status">Searching for attractions…</p>
	{:else if placeState.status === 'searching'}
		<p class="status" role="status">Searching for attractions…</p>
	{:else if placeState.status === 'walking'}
		<p class="status" role="status">Checking walking access…</p>
	{:else if placeState.status === 'ambiguous'}
		<p class="status" role="status">Choose an attraction from the matching places.</p>
	{:else if placeState.status === 'not_found'}
		<p class="status" role="status">No matching attraction was found.</p>
	{:else if placeState.status === 'incomplete'}
		<p class="status" role="status">The place search needs a narrower choice.</p>
	{:else if placeState.status === 'unavailable'}
		<p class="status" role="status">Place lookup is unavailable.</p>
	{/if}

	{#if placeState.error}<p class="error" role="alert">{placeState.error}</p>{/if}

	{#if FALLBACK_STATUSES.has(placeState.status)}
		<div class="fallback">
			<p>Search Google when the place lookup cannot provide a complete, unique result.</p>
			<button type="button" onclick={searchGoogle}>Search Google</button>
			<form class="manual-search" onsubmit={(event) => { event.preventDefault(); selectManual(); }}>
				<fieldset>
					<legend>Enter coordinates</legend>
					<div class="coordinate-fields">
						<label for="attraction-latitude">Latitude</label>
						<input id="attraction-latitude" inputmode="decimal" bind:value={manualLatitude} />
						<label for="attraction-longitude">Longitude</label>
						<input id="attraction-longitude" inputmode="decimal" bind:value={manualLongitude} />
					</div>
					<button type="submit">Use coordinates</button>
				</fieldset>
			</form>
			{#if manualError}<p class="error" role="alert">{manualError}</p>{/if}
		</div>
	{/if}

	{#if placeState.options.length > 0 && placeState.selected === null}
		<ul class="choices" aria-label="Attraction choices">
			{#each placeState.options as option (option.option_ref)}
				<li class="choice">
					<button type="button" class="choice-button" aria-label={choiceLabel(option)} onclick={() => selectAttraction(option.option_ref)}>
						<strong>{option.name}</strong>
					</button>
					<div class="choice-details">
						<span class="source">{sourceLabel(option.source)}</span>
						{#if option.locality}<span>{option.locality}</span>{/if}
						{#if option.address}<span>{option.address}</span>{/if}
					</div>
					{#if option.source === 'google'}
						<p class="attribution">Results from <a href="https://www.google.com/maps" target="_blank" rel="noopener noreferrer">Google Maps</a>.</p>
					{/if}
				</li>
			{/each}
		</ul>
	{/if}

	{#if placeState.selected}
		<section class="selected-attraction" aria-labelledby="selected-attraction-heading">
			<h3 id="selected-attraction-heading">Selected attraction</h3>
			<strong>{placeState.selected.name}</strong>
			{#if placeState.selected.locality}<span>{placeState.selected.locality}</span>{/if}
			{#if placeState.selected.address}<span>{placeState.selected.address}</span>{/if}
			<span class="source">{sourceLabel(placeState.selected.source)}</span>
			{#if placeState.selected.source === 'google'}
				<p class="attribution">Results from <a href="https://www.google.com/maps" target="_blank" rel="noopener noreferrer">Google Maps</a>.</p>
			{/if}
		</section>

		<section class="access" aria-labelledby="access-heading">
			<h3 id="access-heading">Canal access alternatives</h3>
			<p class="access-note">Walking directions describe a route between the canal and attraction. They do not confirm canal access or mooring permission.</p>
			<p class="attribution">Walking directions: <a href="https://www.google.com/maps" target="_blank" rel="noopener noreferrer">Google Maps</a>.</p>
			{#if placeState.access.length === 0}
				<p class="status">No canal access alternatives are available yet.</p>
			{:else}
				<ul class="access-list">
					{#each placeState.access as item (item.candidate.candidate_id)}
						<li class:complete={item.complete} class="access-option">
							<strong>{item.candidate.display_name}</strong>
							<div class="directions">
								<span>To attraction: {transferText(item.outward)}</span>
								<span>Return walk: {transferText(item.return)}</span>
							</div>
							{#if item.complete}
								<label class="confirmation">
									<input
										type="checkbox"
										checked={confirmedCandidate === item.candidate.candidate_id}
										onchange={(event) => toggleConfirmation(item.candidate.candidate_id, event)}
									/>
									I understand canal access and mooring are unconfirmed
								</label>
								{#if onPreview}
									<button
										type="button"
										disabled={confirmedCandidate !== item.candidate.candidate_id || previewingCandidate !== null}
										onclick={() => previewWalk(item.candidate.candidate_id)}
									>
										{previewingCandidate === item.candidate.candidate_id ? 'Loading walk…' : 'Preview walk'}
									</button>
								{/if}
							{:else}
								<p class="incomplete">Both walking directions are required before this option can be previewed.</p>
							{/if}
						</li>
					{/each}
				</ul>
			{/if}
			{#if previewError}<p class="error" role="alert">{previewError}</p>{/if}
		</section>
	{/if}

	<button type="button" class="clear" onclick={clearAttraction}>Clear attraction</button>
</section>

<style>
	.attraction-panel { display: grid; gap: 0.8rem; }
	.attraction-panel h2, .attraction-panel h3 { margin: 0; }
	.attraction-panel h2 { font-size: 1.1rem; }
	.attraction-panel h3 { font-size: 0.95rem; }
	.intro, .status, .access-note, .incomplete, .attribution { margin: 0; color: #536861; font-size: 0.86rem; }
	.search-actions { display: flex; gap: 0.45rem; }
	.search-actions input { flex: 1; min-width: 0; }
	.fallback, .selected-attraction, .access { display: grid; gap: 0.55rem; padding: 0.75rem; border: 1px solid #d8e0dc; border-radius: 8px; }
	.fallback { background: #fff6dc; border-color: #ead5a0; }
	.manual-search fieldset { display: grid; gap: 0.45rem; margin: 0; padding: 0; border: 0; }
	.manual-search legend { font-weight: 700; font-size: 0.88rem; }
	.coordinate-fields { display: grid; grid-template-columns: 1fr 1fr; gap: 0.45rem; }
	.coordinate-fields input { min-width: 0; padding: 0.55rem; border: 1px solid #9aaca6; border-radius: 6px; font: inherit; }
	.choices, .access-list { display: grid; gap: 0.5rem; list-style: none; padding: 0; margin: 0; }
	.choice, .access-option { padding: 0.7rem; border: 1px solid #d8e0dc; border-radius: 8px; }
	.choice-button { width: 100%; text-align: left; background: transparent; color: #18302b; padding: 0; }
	.choice-details, .directions { display: flex; gap: 0.7rem; flex-wrap: wrap; margin-top: 0.35rem; color: #536861; font-size: 0.84rem; }
	.source { color: #08745c; font-size: 0.75rem; font-weight: 700; text-transform: uppercase; }
	.attribution { margin-top: 0.35rem; }
	.selected-attraction > span { color: #536861; }
	.access-note { color: #7f391f; }
	.directions span { display: block; }
	.confirmation { display: flex; gap: 0.45rem; align-items: flex-start; margin-top: 0.6rem; font-weight: 600; font-size: 0.82rem; }
	.confirmation input { margin-top: 0.2rem; }
	.access-option button { margin-top: 0.6rem; }
	.access-option button:disabled { cursor: not-allowed; opacity: 0.5; }
	.error { margin: 0; padding: 0.6rem; background: #fff0ec; border-left: 4px solid #b43b22; }
	.clear { justify-self: start; background: transparent; color: #08745c; border: 1px solid #08745c; }
</style>
