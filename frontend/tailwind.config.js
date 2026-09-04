/** @type {import('tailwindcss').Config} */
//
// The palette follows Redash's own theme variables, so the platform reads like
// the tool people already have open in the next tab. The values are its:
// #2196f3 primary, #edecec page, #e8e8e8 borders, #595959 body text, #333
// headings, and the #191C22 navy its sidebar has always been.
//
// The chart series palette is deliberately not from here - it is validated for
// colour-vision deficiency separation in lib/charts.ts, and a chart's colours
// carry meaning that page furniture does not.
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  theme: {
    extend: {
      colors: {
        // Material blue, which is where Redash's @primary-color sits.
        brand: {
          50: '#e3f2fd',
          100: '#bbdefb',
          200: '#90caf9',
          300: '#64b5f6',
          400: '#42a5f5',
          500: '#2196f3',
          600: '#1e88e5',
          700: '#1976d2',
          800: '#1565c0',
          900: '#0d47a1',
        },
        ink: {
          50: '#f7f8f9',
          100: '#edecec', // @body-bg
          200: '#e8e8e8', // @border-color-base
          300: '#d9d9d9',
          400: '#b4b4b4', // @input-color-placeholder
          500: '#8c8c8c',
          600: '#767676', // @text-color
          700: '#595959', // @input-color
          800: '#444444',
          900: '#333333', // @headings-color
        },
        // The sidebar is the one dark surface, and its own three values.
        sidebar: {
          DEFAULT: '#191c22',
          active: '#121419',
          text: '#9ba1b1',
        },
        // Links are a shade of cyan rather than the primary blue.
        link: '#02a4c4',
      },
      fontFamily: {
        sans: [
          '-apple-system',
          'BlinkMacSystemFont',
          'Segoe UI',
          'Roboto',
          'Oxygen-Sans',
          'Ubuntu',
          'Cantarell',
          'Helvetica Neue',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'monospace'],
      },
      borderRadius: {
        // Redash is a square-cornered interface: 3px on panels, 2px on controls.
        card: '3px',
        control: '2px',
      },
      boxShadow: {
        card: '0 1px 3px rgba(0,0,0,.05)',
        pop: '0 4px 12px rgba(0,0,0,.15)',
      },
    },
  },
  plugins: [],
}
