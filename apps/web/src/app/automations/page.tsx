import { notFound } from "next/navigation";
import { AUTOMATIONS_ENABLED } from "@/lib/automations/feature-flag";
import { AutomationsClient } from "./automations-client";

export default function AutomationsPage() {
  // Feature-flag gate — when disabled, render Next 404. Performed in the
  // server component so the gate runs before any client hooks mount.
  if (!AUTOMATIONS_ENABLED) {
    notFound();
  }
  return <AutomationsClient />;
}
