import { spawn } from "node:child_process";

const epubPath = process.argv[2];
const jarPath = process.env.EPUBCHECK_JAR;

if (!epubPath || !jarPath) {
  console.error("Usage: EPUBCHECK_JAR=/path/to/epubcheck.jar npm run epubcheck -- book.epub");
  process.exit(1);
}

const child = spawn("java", ["-jar", jarPath, epubPath], {
  stdio: "inherit"
});

child.on("exit", (code) => {
  process.exit(code ?? 1);
});

