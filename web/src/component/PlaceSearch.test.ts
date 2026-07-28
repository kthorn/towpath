import { render, screen, waitFor } from '@testing-library/svelte';
import { expect, it, vi } from 'vitest';
import type { SelectedPlace } from '../lib/google/contracts';
import PlaceSearch from './PlaceSearch.svelte';

it('clears a provider error after a later successful selection', async () => {
  let select!: (place: SelectedPlace) => void;
  let unavailable!: (error: unknown) => void;
  const attach = vi.fn((
    _container: HTMLElement,
    onSelect: (place: SelectedPlace) => void,
    onUnavailable?: (error: unknown) => void,
  ) => {
    select = onSelect;
    unavailable = onUnavailable!;
    return vi.fn();
  });
  render(PlaceSearch, {
    props: { label: 'Search origin', search: { attach }, onselect: vi.fn() },
  });

  await waitFor(() => expect(attach).toHaveBeenCalledOnce());
  unavailable(new Error('provider failed'));
  await waitFor(() => expect(screen.getByRole('alert')).toHaveTextContent(
    'Place search unavailable: provider failed.',
  ));

  select({ name: 'Recovered place', address: '', coordinate: { lat: 51, lon: -1 } });

  await waitFor(() => expect(screen.queryByRole('alert')).not.toBeInTheDocument());
});

it('mounts the provider search on an element container', async () => {
  const attach = vi.fn((_container: HTMLElement) => vi.fn());
  render(PlaceSearch, {
    props: { label: 'Search origin', search: { attach }, onselect: vi.fn() },
  });

  await waitFor(() => expect(attach).toHaveBeenCalledOnce());
  expect(attach.mock.calls[0][0]).toBeInstanceOf(HTMLElement);
  expect(attach.mock.calls[0][0]).not.toBeInstanceOf(HTMLInputElement);
});

it('calls provider cleanup when the search unmounts', async () => {
  const cleanup = vi.fn();
  const attach = vi.fn((_container: HTMLElement) => cleanup);
  const rendered = render(PlaceSearch, {
    props: { label: 'Search origin', search: { attach }, onselect: vi.fn() },
  });

  await waitFor(() => expect(attach).toHaveBeenCalledOnce());
  rendered.unmount();
  expect(cleanup).toHaveBeenCalledOnce();
});
