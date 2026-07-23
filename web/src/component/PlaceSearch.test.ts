import { render, waitFor } from '@testing-library/svelte';
import { describe, expect, it, vi } from 'vitest';
import PlaceSearch from './PlaceSearch.svelte';

it('mounts the provider search on an element container', async () => {
  const attach = vi.fn((_container: HTMLElement) => vi.fn());
  render(PlaceSearch, {
    props: { label: 'Search origin', search: { attach }, onselect: vi.fn() },
  });

  await waitFor(() => expect(attach).toHaveBeenCalledOnce());
  expect(attach.mock.calls[0][0]).toBeInstanceOf(HTMLElement);
  expect(attach.mock.calls[0][0]).not.toBeInstanceOf(HTMLInputElement);
});
