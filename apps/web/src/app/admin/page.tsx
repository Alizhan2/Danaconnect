import { redirect } from 'next/navigation';

export const dynamic = 'force-dynamic';

export default function AdminEntry(){
  redirect(process.env.ADMIN_APP_URL || 'http://127.0.0.1:3001');
}