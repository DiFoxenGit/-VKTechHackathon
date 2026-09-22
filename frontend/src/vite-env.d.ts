/// <reference types="vite/client" />

interface ImportMetaEnv {
  /** Base URL of the backend API including the version prefix, e.g. /api/v1 */
  readonly VITE_API_URL?: string;
  /** Shared Bearer token when the backend runs with DESIGNER_API_KEY */
  readonly VITE_API_TOKEN?: string;
}

interface ImportMeta {
  readonly env: ImportMetaEnv;
}
