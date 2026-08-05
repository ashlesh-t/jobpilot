/** Tailwind config — every colour is a CSS variable so light and dark are one token set.
 *  See src/styles/theme.css for the values. */
export default {
  content: ['./index.html', './src/**/*.{ts,tsx}'],
  darkMode: ['class', ':root[data-theme="dark"]'],
  theme: {
    extend: {
      colors: {
        canvas: 'rgb(var(--canvas) / <alpha-value>)',
        surface: 'rgb(var(--surface) / <alpha-value>)',
        raised: 'rgb(var(--raised) / <alpha-value>)',
        line: 'rgb(var(--line) / <alpha-value>)',
        ink: 'rgb(var(--ink) / <alpha-value>)',
        muted: 'rgb(var(--muted) / <alpha-value>)',
        faint: 'rgb(var(--faint) / <alpha-value>)',
        accent: {
          DEFAULT: 'rgb(var(--accent) / <alpha-value>)',
          soft: 'rgb(var(--accent-soft) / <alpha-value>)',
          ink: 'rgb(var(--accent-ink) / <alpha-value>)',
        },
        ok: 'rgb(var(--ok) / <alpha-value>)',
        warn: 'rgb(var(--warn) / <alpha-value>)',
        danger: 'rgb(var(--danger) / <alpha-value>)',
        info: 'rgb(var(--info) / <alpha-value>)',
      },
      // System fonts only. Shipping a webfont would mean either a network request
      // (breaking offline use) or a few hundred KB in the wheel for a marginal gain.
      fontFamily: {
        sans: [
          'system-ui',
          '-apple-system',
          'Segoe UI',
          'Roboto',
          'Helvetica Neue',
          'Arial',
          'sans-serif',
        ],
        mono: ['ui-monospace', 'SFMono-Regular', 'Menlo', 'Consolas', 'monospace'],
      },
      borderRadius: {
        xl: '0.75rem',
        '2xl': '1rem',
      },
      boxShadow: {
        card: '0 1px 2px 0 rgb(var(--shadow-color) / 0.04), 0 1px 3px 0 rgb(var(--shadow-color) / 0.06)',
        // Elevated resting state for interactive cards (stat tiles, job rows) —
        // one step up from `card`, still subtle enough for a dense dashboard.
        float: '0 4px 12px -4px rgb(var(--shadow-color) / 0.14), 0 2px 4px -2px rgb(var(--shadow-color) / 0.08)',
        pop: '0 8px 24px -6px rgb(var(--shadow-color) / 0.18), 0 2px 6px -2px rgb(var(--shadow-color) / 0.10)',
        // A soft accent-tinted glow for the primary button's hover state — reads as
        // "this is the one to click," not just a darker fill.
        glow: '0 1px 0 0 rgb(255 255 255 / 0.15) inset, 0 4px 16px -2px rgb(var(--accent) / 0.45)',
      },
      keyframes: {
        'fade-in': { from: { opacity: '0' }, to: { opacity: '1' } },
        'slide-up': {
          from: { opacity: '0', transform: 'translateY(6px)' },
          to: { opacity: '1', transform: 'translateY(0)' },
        },
        shimmer: {
          '100%': { transform: 'translateX(100%)' },
        },
        'pulse-ring': {
          '0%': { transform: 'scale(0.9)', opacity: '0.6' },
          '80%, 100%': { transform: 'scale(1.6)', opacity: '0' },
        },
      },
      animation: {
        'fade-in': 'fade-in 160ms ease-out',
        'slide-up': 'slide-up 180ms ease-out',
        shimmer: 'shimmer 1.6s infinite',
        'pulse-ring': 'pulse-ring 1.8s cubic-bezier(0.2, 0.6, 0.4, 1) infinite',
      },
      transitionTimingFunction: {
        // A gentle overshoot — used on hover/press micro-interactions (buttons,
        // cards) so they feel tactile instead of just linear-fading.
        spring: 'cubic-bezier(0.34, 1.56, 0.64, 1)',
      },
    },
  },
  plugins: [],
}
