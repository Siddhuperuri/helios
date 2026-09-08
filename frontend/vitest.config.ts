import { fileURLToPath } from 'node:url';

import react from '@vitejs/plugin-react';
import { defineConfig } from 'vitest/config';

/**
 * Test configuration.
 *
 * `jsdom` rather than a real browser: these tests cover logic and component behaviour,
 * and the things a real browser is genuinely needed for — tile loading, pointer gestures,
 * geolocation prompts — are verified by driving the running application instead. Pretending
 * jsdom tests those would be worse than not writing them.
 */
export default defineConfig({
  plugins: [react()],
  test: {
    environment: 'jsdom',
    globals: true,
    include: ['tests/**/*.test.{ts,tsx}'],
    restoreMocks: true,
  },
  resolve: {
    alias: {
      '@': fileURLToPath(new URL('./', import.meta.url)),
    },
  },
});
