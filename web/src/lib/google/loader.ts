export const GOOGLE_MAPS_LIBRARIES = ['maps', 'places', 'routes', 'marker'] as const;
export type GoogleMapsLibraryName = (typeof GOOGLE_MAPS_LIBRARIES)[number];

export interface GoogleBootstrap {
  importLibrary(name: GoogleMapsLibraryName): Promise<unknown>;
}

export interface GoogleMapsModules {
  maps: unknown;
  places: unknown;
  routes: unknown;
  marker: unknown;
}

export type GoogleSdkFacade = GoogleMapsModules;

export type GoogleScriptLoader = (apiKey: string) => Promise<GoogleBootstrap>;

function errorMessage(error: unknown): string {
  return error instanceof Error ? error.message : String(error);
}

async function importRequiredLibraries(bootstrap: GoogleBootstrap): Promise<GoogleSdkFacade> {
  const entries = await Promise.all(
    GOOGLE_MAPS_LIBRARIES.map(async (name) => {
      try {
        return [name, await bootstrap.importLibrary(name)] as const;
      } catch (error) {
        throw new Error(`${name} library: ${errorMessage(error)}`);
      }
    }),
  );
  return Object.fromEntries(entries) as unknown as GoogleSdkFacade;
}

export function createGoogleMapsLoader(loadScript: GoogleScriptLoader) {
  let pending: Promise<GoogleSdkFacade> | undefined;

  return {
    load(apiKey: string): Promise<GoogleSdkFacade> {
      if (!apiKey) return Promise.reject(new Error('Failed to load Google Maps: API key is required'));
      if (pending) return pending;

      pending = loadScript(apiKey)
        .then(importRequiredLibraries)
        .catch((error: unknown) => {
          pending = undefined;
          throw new Error(`Failed to load Google Maps: ${errorMessage(error)}`);
        });
      return pending;
    },
  };
}

export function createBrowserScriptLoader(documentRef: Document = document): GoogleScriptLoader {
  return (apiKey) =>
    new Promise((resolve, reject) => {
      const callbackName = `__poundGoogleMapsReady_${crypto.randomUUID().replaceAll('-', '')}`;
      const globalRef = window as unknown as Record<string, unknown>;
      const script = documentRef.createElement('script');
      const cleanup = () => delete globalRef[callbackName];

      globalRef[callbackName] = () => {
        cleanup();
        const google = (window as unknown as { google?: { maps?: GoogleBootstrap } }).google;
        if (google?.maps) resolve(google.maps);
        else reject(new Error('SDK initialized without the Maps namespace'));
      };
      script.async = true;
      script.src = `https://maps.googleapis.com/maps/api/js?key=${encodeURIComponent(apiKey)}&loading=async&callback=${callbackName}`;
      script.onerror = () => {
        cleanup();
        script.remove();
        reject(new Error('script request failed'));
      };
      documentRef.head.append(script);
    });
}

export const googleMapsLoader = createGoogleMapsLoader(createBrowserScriptLoader());
