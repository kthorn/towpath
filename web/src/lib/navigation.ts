import { writable, type Readable } from 'svelte/store';

export type AppRoute = 'planner' | 'settings';

export interface NavigationEnvironment {
  location: Pick<Location, 'pathname'>;
  history: Pick<History, 'pushState' | 'replaceState'>;
  addEventListener(type: 'popstate', listener: () => void): void;
  removeEventListener(type: 'popstate', listener: () => void): void;
}

export interface Navigation extends Readable<AppRoute> {
  navigate(route: AppRoute): void;
  href(route: AppRoute): string;
  destroy(): void;
}

export function parseRoute(pathname: string): AppRoute {
  return pathname === '/settings' || pathname === '/settings/' ? 'settings' : 'planner';
}

function routePath(route: AppRoute): string {
  return route === 'settings' ? '/settings' : '/';
}

function isCanonical(pathname: string): boolean {
  return pathname === '/' || pathname === '/settings';
}

export function createNavigation(environment?: NavigationEnvironment): Navigation {
  const env: NavigationEnvironment = environment ?? {
    location: globalThis.location,
    history: globalThis.history,
    addEventListener: (type, listener) => globalThis.addEventListener(type, listener),
    removeEventListener: (type, listener) => globalThis.removeEventListener(type, listener),
  };

  // Normalize initial path if needed
  const initialRoute = parseRoute(env.location.pathname);
  const canonicalPath = routePath(initialRoute);
  if (env.location.pathname !== canonicalPath) {
    env.history.replaceState(null, '', canonicalPath);
  }

  const inner = writable<AppRoute>(initialRoute);

  let currentRoute = initialRoute;

  const unsubscribeFromInner = inner.subscribe((value) => {
    currentRoute = value;
  });

  let destroyed = false;

  const onPopState = () => {
    if (destroyed) return;

    const route = parseRoute(env.location.pathname);
    const canonical = routePath(route);

    // Canonicalize the URL if needed on popstate
    if (env.location.pathname !== canonical) {
      env.history.replaceState(null, '', canonical);
    }

    // Only publish if the route actually changed
    if (route !== currentRoute) {
      inner.set(route);
    }
  };

  env.addEventListener('popstate', onPopState);

  return {
    subscribe: inner.subscribe,
    navigate(route: AppRoute) {
      if (route === currentRoute) return;
      const path = routePath(route);
      env.history.pushState(null, '', path);
      inner.set(route);
    },
    href(route: AppRoute): string {
      return routePath(route);
    },
    destroy() {
      if (destroyed) return;
      destroyed = true;
      env.removeEventListener('popstate', onPopState);
      unsubscribeFromInner();
    },
  };
}
