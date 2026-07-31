import nextVitals from "eslint-config-next/core-web-vitals";
import nextTs from "eslint-config-next/typescript";

const eslintConfig = [
  ...nextVitals,
  ...nextTs,
  {
    ignores: [
      ".next/**",
      "node_modules/**",
      "coverage/**",
      "tmp/**",
      "testsets/pdfs/**",
      "testsets/screenshots/**",
      "testsets/epubs/**",
      "testsets/reports/**"
    ]
  }
];

export default eslintConfig;
