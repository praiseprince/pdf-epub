import { redirect } from "next/navigation";
import { ConvertClient } from "./convert-client";
import { hasValidSession } from "@/lib/auth/session";

export default async function ConvertPage() {
  if (!(await hasValidSession())) {
    redirect("/login");
  }

  return (
    <main className="screen">
      <ConvertClient />
    </main>
  );
}

