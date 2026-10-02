import { SupportPage } from '@/components/support';

export default async function Page({searchParams}: {searchParams: Promise<Record<string,string|string[]|undefined>>}) {
  const query = await searchParams;
  return <SupportPage contextType={typeof query.type === 'string' ? query.type : ''} contextEntity={typeof query.entity === 'string' ? query.entity : ''}/>;
}
