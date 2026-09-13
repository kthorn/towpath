# Responsive climate overlay and adjustable colour scale

The nationwide raster was recomputed inside map animation frames. A browser
Ctrl-scroll sequence on the deployed version triggered 18 raster computations;
the longest animation callback was about 1.9 seconds. Rare hot-day probabilities
also looked indistinguishable from zero on the fixed 0–100% colour scale. The live
June 26–July 2, 2001–2025 surface has 443 nonzero cells among 2,961 available cells,
with a maximum of 3/175 days (about 1.7%).

The overlay now repositions its completed image using geographic corner anchors
while the map moves. It waits 150 ms after the last draw to resample. Temperature
rows and coastline projection/tracing yield between animation frames with a 6 ms
work budget. An offscreen replacement is committed only when complete. New map
movement, data, colour bounds, disable, or destruction cancels unfinished work.
The final browser profile completed one raster after the gesture sequence, with
no raster callback longer than 8.8 ms in that run. These are local browser
measurements, not a guarantee for every device or map configuration.

Users can adjust both colour bounds, zoom the colour range in/out, and restore
Auto. These display-only changes do not fetch temperatures. Auto probability
bounds start at zero and use the nearest-rank 99.9th percentile across all finite,
available UK grid cells as the maximum. This permits approximately 0.1% of cells
to exceed the colour maximum; ties and spatial smoothing affect the visible pixel
fraction. The range is independent of the viewport. If the percentile is zero,
the maximum nonzero probability is used so isolated hot cells remain visible;
an all-zero or unavailable surface uses a nondegenerate 0–1% display range.
Temperature Auto retains the existing high/low limits. Changing views restores
Auto to avoid carrying incompatible units between metrics.

Colour interpolation remains linear between the displayed bounds. Values outside
the bounds saturate, while cell details retain exact empirical values. Adaptive
legend precision keeps narrow ranges readable. Controls report the number of cells
with recorded exceedances and retain the warning that zero observations does not
rule out hotter weather. Data, thresholds, and historical distribution semantics
are unchanged.

Regression coverage includes gesture cancellation, incremental temperature and
coastline work, scale percentile/fallbacks, manual limits and zoom, invalid input,
narrow legend precision, view resets, and App-to-map propagation without API calls.

Validation: 341 frontend tests passed, Svelte reported zero errors/warnings, and
the production build succeeded. A browser exercise of both bounds, colour zoom,
and Auto generated zero additional grid API requests and no page errors. At the
live default week, the automatic probability maximum was 1.71428571429%. Independent
review covered scale validation/precision and renderer cancellation/lifecycle.
