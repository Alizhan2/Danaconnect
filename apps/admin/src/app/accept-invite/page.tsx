import type {Metadata} from 'next';
import {AcceptAdminInvitation} from '@/components/accept-admin-invitation';

export const metadata:Metadata={title:'Administrator invitation',referrer:'no-referrer',robots:{index:false,follow:false}};

export default function Page(){return <AcceptAdminInvitation/>;}
