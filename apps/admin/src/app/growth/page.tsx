"use client";
import { AdminShell } from "@/components/shell";
import { GrowthAdministration } from "@/components/growth/admin-growth";
export default function GrowthPage() {
  return (
    <AdminShell title="growth">
      <GrowthAdministration />
    </AdminShell>
  );
}
