'use client';
import { AdminShell } from '@/components/shell';
import { PilotLaunch } from '@/components/launch';

export default function Page() {
  return <AdminShell title="launch"><PilotLaunch /></AdminShell>;
}
