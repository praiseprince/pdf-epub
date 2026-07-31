import bcrypt from "bcryptjs";
import { readRequiredEnv } from "@/lib/server/env";

const MIN_RECOMMENDED_PIN_LENGTH = 8;

export async function verifyPin(pin: string, hash = readRequiredEnv("APP_PIN_HASH")) {
  if (!pin) {
    return false;
  }

  return bcrypt.compare(pin, hash);
}

export async function hashPin(pin: string, rounds = 12) {
  if (pin.length < MIN_RECOMMENDED_PIN_LENGTH) {
    throw new Error("Use at least eight characters for the public app PIN.");
  }

  return bcrypt.hash(pin, rounds);
}

