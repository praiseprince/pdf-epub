"use client";

import { useRouter } from "next/navigation";
import { useState } from "react";

export function LoginForm() {
  const router = useRouter();
  const [pin, setPin] = useState("");
  const [error, setError] = useState("");
  const [pending, setPending] = useState(false);

  async function submit(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setPending(true);
    setError("");

    const response = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ pin })
    });

    setPending(false);
    if (!response.ok) {
      const body = (await response.json().catch(() => null)) as { error?: string } | null;
      setError(body?.error ?? "The PIN was not accepted.");
      return;
    }

    router.replace("/convert");
    router.refresh();
  }

  return (
    <form className="stack" onSubmit={submit}>
      <label className="field">
        <span>PIN</span>
        <input
          className="input"
          autoComplete="current-password"
          inputMode="text"
          type="password"
          value={pin}
          minLength={1}
          onChange={(event) => setPin(event.target.value)}
          disabled={pending}
          required
        />
      </label>
      {error ? <p className="error">{error}</p> : null}
      <button className="button" type="submit" disabled={pending}>
        {pending ? "Unlocking" : "Unlock"}
      </button>
    </form>
  );
}

