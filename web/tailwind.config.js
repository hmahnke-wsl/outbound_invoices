import sharedPreset from '@wsl/ui/tailwind-preset';

/** @type {import('tailwindcss').Config} */
export default {
  presets: [sharedPreset],
  content: ['./index.html', './src/**/*.{ts,tsx}', '../../shared_ui/src/**/*.{ts,tsx}'],
};
