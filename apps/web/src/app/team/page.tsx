'use client';
import { api } from '@/lib/api';
import type { User } from '@/lib/types';
import { useLocale } from '@/lib/i18n';
import { AppShell } from '@/components/shell';
import { LoadState, useLoad } from '@/components/workflows/common';
import { InvitationList } from '@/components/collaboration';
import { TeamMemberships } from '@/components/team-memberships';

export default function TeamPage() {
  const { tr } = useLocale();
  const load = useLoad(() => api<User>('/auth/me'));
  return <AppShell title={tr('Команда и приглашения')} description={tr('Входящие приглашения в проекты и приглашения вашей команды.')} dashboard><LoadState {...load} retry={load.reload}>{load.data && <div className="stack"><TeamMemberships user={load.data}/><InvitationList user={load.data} /></div>}</LoadState></AppShell>;
}
