import { notFound } from "next/navigation";
import { AUTOMATIONS_ENABLED } from "@/lib/automations/feature-flag";
import { AdminAutomationsClient } from "./admin-automations-client";

export default function AdminAutomationsPage() {
  // Feature-flag gate runs at the server-component layer so it executes
  // before any client hooks mount.
  if (!AUTOMATIONS_ENABLED) {
    notFound();
  }
  return <AdminAutomationsClient />;
}
