"use client";
import { AdminShell } from "@/components/shell";
import { ActivityAdministration } from "@/components/activity";
export default function Page() {
  return (
    <AdminShell title="activity">
      <ActivityAdministration />
    </AdminShell>
  );
}
