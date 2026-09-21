const DEFAULT_BACKEND_URLS = [
  "http://127.0.0.1:8000",
  "http://localhost:8000",
  "http://127.0.0.1:8765",
  "http://localhost:8765"
];

function splitUrls(value: string | undefined): string[] {
  if (!value) {
    return [];
  }

  return value
    .split(",")
    .map((url) => url.trim())
    .filter(Boolean);
}

function uniqueUrls(urls: string[]): string[] {
  return Array.from(new Set(urls.map((url) => url.replace(/\/+$/, ""))));
}

export function getBackendBaseUrls(): string[] {
  const port = process.env.BACKEND_PORT || process.env.NEXT_PUBLIC_BACKEND_PORT;
  const portUrls = port
    ? [`http://127.0.0.1:${port}`, `http://localhost:${port}`]
    : [];

  return uniqueUrls([
    ...splitUrls(process.env.API_BASE_URLS),
    ...splitUrls(process.env.NEXT_PUBLIC_API_BASE_URLS),
    ...splitUrls(process.env.API_BASE_URL),
    ...splitUrls(process.env.NEXT_PUBLIC_API_BASE_URL),
    ...portUrls,
    ...DEFAULT_BACKEND_URLS
  ]);
}

export async function postToBackend(path: string, body: unknown): Promise<Response> {
  const errors: string[] = [];

  for (const baseUrl of getBackendBaseUrls()) {
    try {
      return await fetch(`${baseUrl}${path}`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json"
        },
        body: JSON.stringify(body)
      });
    } catch (error) {
      const message = error instanceof Error ? error.message : "Error desconocido";
      errors.push(`${baseUrl}: ${message}`);
    }
  }

  throw new Error(errors.join(" | "));
}
