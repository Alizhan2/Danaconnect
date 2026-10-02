import type { Metadata } from 'next';
import { LocaleProvider } from '@/lib/i18n';
import './globals.css';
export const metadata: Metadata = {title:{default:'DanaConnect · Admin',template:'%s · DanaConnect Admin'},description:'DanaConnect administration console'};
export default function RootLayout({children}:{children:React.ReactNode}){return <html lang="ru"><body><LocaleProvider>{children}</LocaleProvider></body></html>;}
