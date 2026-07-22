// PostCSS runs Tailwind (which generates utility classes) and Autoprefixer (which
// adds vendor prefixes for browser compatibility). Vite picks this file up automatically.
// Written with `export default` because package.json sets "type": "module".
export default {
  plugins: {
    tailwindcss: {},
    autoprefixer: {},
  },
};
