import { redirect } from "next/navigation";
import { LoginForm } from "./login-form";
import { hasValidSession } from "@/lib/auth/session";

export default async function LoginPage() {
  if (await hasValidSession()) {
    redirect("/convert");
  }

  return (
    <main className="screen">
      <section className="panel narrow stack" aria-labelledby="login-title">
        <div>
          <p className="kicker">Private converter</p>
          <h1 id="login-title">Enter your PIN</h1>
          <p>
            This personal app is locked before uploads. Use a long PIN or passcode because the
            deployment URL is public.
          </p>
        </div>
        <LoginForm />
      </section>
    </main>
  );
}

