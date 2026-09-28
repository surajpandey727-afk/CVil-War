module.exports = {
  root: true,
  env: { browser: true, es2020: true },
  extends: [
    'eslint:recommended',
    'plugin:@typescript-eslint/recommended',
    'plugin:react-hooks/recommended',
  ],
  ignorePatterns: ['dist', '.eslintrc.cjs'],
  parser: '@typescript-eslint/parser',
  plugins: ['react-refresh'],
  rules: {
    'react-refresh/only-export-components': [
      'warn',
      { allowConstantExport: true },
    ],
    '@typescript-eslint/no-explicit-any': 'error',
    '@typescript-eslint/no-unused-vars': [
      'error',
      {
        argsIgnorePattern: '^_',
        // `const { [key]: _drop, ...rest } = obj` is how you omit a property without
        // mutating the original. The binding is unused by design -- naming it is the
        // mechanism, not an oversight -- and this option exists for exactly that idiom.
        ignoreRestSiblings: true,
        varsIgnorePattern: '^_',
      },
    ],
  },
};
