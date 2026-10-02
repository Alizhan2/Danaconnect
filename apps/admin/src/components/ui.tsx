import Link from 'next/link';
import { ArrowRight, Inbox } from 'lucide-react';
import type { ButtonHTMLAttributes, ReactNode } from 'react';
type ButtonProps = ButtonHTMLAttributes<HTMLButtonElement> & {href?:string;variant?:'primary'|'secondary'|'ghost'|'accent'|'danger';children:ReactNode};
export function Button({href,variant='primary',children,className='',disabled,...props}:ButtonProps) {
  const cls=`button button-${variant} ${className}`;
  if (href && !disabled) return <Link href={href} className={cls}>{children}</Link>;
  return <button type="button" disabled={disabled} {...props} className={cls}>{children}</button>;
}
export function Badge({children,tone='neutral'}:{children:ReactNode;tone?:'neutral'|'success'|'warning'|'danger'|'blue'|'gold'}) {return <span className={`badge badge-${tone}`}>{children}</span>;}
export function Field({label,children,hint}:{label:string;children:ReactNode;hint?:string}) {return <label className="field"><span className="field-label">{label}</span>{children}{hint&&<span className="field-hint">{hint}</span>}</label>;}
export function EmptyState({title,description,action}:{title:string;description?:string;action?:ReactNode}) {return <div className="empty-state"><Inbox size={30} strokeWidth={1.4}/><h3>{title}</h3>{description&&<p>{description}</p>}{action}</div>;}
export function SectionHeading({eyebrow,title,description,action}:{eyebrow?:string;title:string;description?:string;action?:ReactNode}) {return <div className="section-heading"><div>{eyebrow&&<p className="eyebrow">{eyebrow}</p>}<h2>{title}</h2>{description&&<p className="muted">{description}</p>}</div>{action}</div>;}
export function TextLink({href,children}:{href:string;children:ReactNode}) {return <Link href={href} className="text-link">{children}<ArrowRight size={16}/></Link>;}
