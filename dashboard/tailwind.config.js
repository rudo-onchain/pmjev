export default {
  content: [
  './index.html',
  './src/**/*.{js,ts,jsx,tsx}'
],
  theme: {
    extend: {
      colors: {
        canvas: '#111317',
        surface: '#181b20',
        raised: '#22262d',
        line: '#2b3038',
        'line-soft': '#23272e',
        ink: '#eef0f3',
        muted: '#9ba3ae',
        subtle: '#7c8591',
        profit: '#3ecf8e',
        loss: '#f2686a',
        warn: '#e6b04e',
        info: '#7ea6f0',
      },
      fontFamily: {
        sans: ['Inter', 'ui-sans-serif', 'system-ui', 'sans-serif'],
      },
    },
  },
};
