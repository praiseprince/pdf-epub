import { randomBytes } from "node:crypto";
import { hashPin } from "../src/lib/auth/password";

function secret() {
  return randomBytes(32).toString("base64url");
}

async function main() {
  const pin = process.argv[2];
  if (!pin) {
    console.error("Usage: npm run generate-secrets -- <your-pin-or-passcode>");
    process.exitCode = 1;
    return;
  }

  const appPinHash = await hashPin(pin);
  console.log(`APP_PIN_HASH=${appPinHash}`);
  console.log(`SESSION_SECRET=${secret()}`);
  console.log(`JOB_TOKEN_SECRET=${secret()}`);
  console.log(`CRON_SECRET=${secret()}`);
  console.log("");
  console.log("Store these values once. Do not commit them.");
}

main().catch((error: unknown) => {
  console.error(error instanceof Error ? error.message : "Failed to generate secrets.");
  process.exitCode = 1;
});

