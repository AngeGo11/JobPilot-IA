/**
 * Configuration Tailwind pour la compilation locale (`make css`).
 *
 * Elle reprend à l'identique la configuration qui était déclarée en ligne dans
 * les gabarits du temps du CDN, afin que le rendu ne change pas.
 *
 * Le scan `content` couvre les gabarits ET le JavaScript qu'ils contiennent :
 * Tailwind lit le fichier comme du texte brut, donc les classes littérales
 * passées à `classList.add('bg-red-100', …)` sont bien détectées. Seules les
 * classes construites dynamiquement (concaténation, template string) doivent
 * figurer dans `safelist`.
 */
module.exports = {
  content: ['./templates/**/*.html'],
  safelist: [
    // Classes assemblées en JS dans administration/supervision.html
    'bg-emerald-500', 'bg-amber-500', 'bg-red-500', 'bg-slate-400',
    // États du toggle d'alerte et des toasts
    'translate-x-1', 'translate-x-5', 'rotate-180',
  ],
  theme: {
    extend: {
      // Les gabarits d'authentification utilisent `text-brand-600` /
      // `hover:text-brand-700` depuis toujours, sans qu'aucune palette `brand`
      // n'ait jamais été définie : ces liens héritaient donc de la couleur du
      // texte. On déclare la palette autour du bleu de marque #125484.
      colors: {
        brand: {
          50: '#eef6fc',
          100: '#d6e9f6',
          200: '#aed3ed',
          300: '#7fb6de',
          400: '#4a90c6',
          500: '#2a6fa5',
          600: '#125484',
          700: '#0f4470',
          800: '#0d375c',
          900: '#0a2b48',
        },
      },
      fontFamily: {
        sans: ['Outfit', 'sans-serif'],
        display: ['Space Grotesk', 'sans-serif'],
      },
    },
  },
  plugins: [],
}
