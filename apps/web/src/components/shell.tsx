"use client";
import Link from "next/link";
import { usePathname } from "next/navigation";
import { useEffect, useRef, useState, type ReactNode } from "react";
import {
  ArrowUpRight,
  Bell,
  CalendarDays,
  BookOpen,
  Trophy,
  CircleUserRound,
  FolderOpen,
  LayoutDashboard,
  LifeBuoy,
  Menu,
  MessageSquare,
  ShieldCheck,
  Users,
  X,
} from "lucide-react";
import { api } from "@/lib/api";
import type { User } from "@/lib/types";
import { useLocale } from "@/lib/i18n";
import { Button } from "./ui";
import { usePlatformStatus } from "./platform-status";
import { statusText } from "./workflows/common";
import { NotificationBell } from "./notification-center";
import { mobileNavigation } from "@/lib/navigation";
import { BrandLogo } from "./brand-logo";
export function AppShell({
  children,
  title,
  description,
  dashboard = false,
}: {
  children: ReactNode;
  title?: string;
  description?: string;
  dashboard?: boolean;
}) {
  const { setLocale, t, locale, tr } = useLocale();
  const { health } = usePlatformStatus();
  const pathname = usePathname();
  const [open, setOpen] = useState(false);
  const menuButton = useRef<HTMLButtonElement>(null);
  const [user, setUser] = useState<User | null>(null);
  useEffect(() => {
    if (!open) return;
    const closeOnEscape = (event: KeyboardEvent) => {
      if (event.key === "Escape") {
        setOpen(false);
        menuButton.current?.focus();
      }
    };
    window.addEventListener("keydown", closeOnEscape);
    return () => window.removeEventListener("keydown", closeOnEscape);
  }, [open]);
  useEffect(() => {
    let live = true;
    let version = 0;
    const refreshUser = () => {
      const current = ++version;
      api<User>("/auth/me")
      .then((value) => {
        if (live && current === version) setUser(value);
      })
      .catch(() => {
        if (live && current === version) setUser(null);
      });
    };
    refreshUser();
    window.addEventListener("danaconnect:profile-updated", refreshUser);
    return () => {
      live = false;
      window.removeEventListener("danaconnect:profile-updated", refreshUser);
    };
  }, [pathname]);
  const nav = [
    { href: "/catalog", label: t.mentors },
    { href: "/projects", label: t.projects },
    { href: "/community", label: t.community },
    { href: "/about", label: t.aboutPlatform },
    { href: "/register", label: t.join },
  ];
  const isActive = (href: string) => pathname === href || pathname.startsWith(`${href}/`) || (href === "/projects" && pathname === "/forum");
  const side = [
    { href: "/dashboard", label: t.dashboard, Icon: LayoutDashboard },
    { href: "/notifications", label: tr("Уведомления"), Icon: Bell },
    { href: "/support", label: tr("Поддержка"), Icon: LifeBuoy },
    { href: "/catalog", label: t.mentors, Icon: Users },
    { href: "/recommendations", label: tr("Подбор ментора"), Icon: Users },
    { href: "/projects", label: t.projects, Icon: FolderOpen },
    { href: "/calendar", label: t.calendar, Icon: CalendarDays },
    { href: "/messages", label: t.messages, Icon: MessageSquare },
    { href: "/team", label: tr("Команда"), Icon: Users },
    { href: "/resources", label: tr("Материалы"), Icon: BookOpen },
    { href: "/achievements", label: tr("Достижения"), Icon: Trophy },
    {
      href: "/privacy",
      label:
        locale === "kk"
          ? "Сіздің деректеріңіз"
          : locale === "en"
            ? "Your data"
            : "Ваши данные",
      Icon: ShieldCheck,
    },
    ...(user?.role === "admin"
      ? [{ href: "/admin", label: t.admin, Icon: ShieldCheck }]
      : []),
  ];
  return (
    <>
      <a className="skip-link" href="#main-content">
        {locale === "ru"
          ? tr("К содержимому")
          : locale === "kk"
            ? "Мазмұнға өту"
            : "Skip to content"}
      </a>
      {health?.demo_mode && (
        <div className="demo-strip">
          <span className="demo-dot" />
          {t.demo}
          <span className="demo-detail">{t.demoNote}</span>
        </div>
      )}
      <header className="header">
        <div className="header-inner">
          <Link className="wordmark" href="/" aria-label={tr("Главная")}>
            <BrandLogo preload secondary /><span className="brand-platform-name">{t.heroEyebrow}</span>
          </Link>
          <nav className="desktop-nav" aria-label={tr("Основная навигация")}>
            {nav.map((item) => (
              <Link
                key={item.href}
                href={item.href}
                className={isActive(item.href) ? "active" : ""}
                aria-current={isActive(item.href) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
          </nav>
          <div className="header-actions">
            {user && <NotificationBell userId={user.id} pathname={pathname} />}
            <select
              className="locale-select"
              aria-label="Язык / Тіл / Language"
              value={locale}
              onChange={(event) =>
                setLocale(event.target.value as "ru" | "kk" | "en")
              }
            >
              <option value="kk">KZ</option>
              <option value="ru">RU</option>
              <option value="en">EN</option>
            </select>
            <Button
              href={user ? "/dashboard" : "/login"}
              variant="secondary"
              className="header-signin"
            >
              {user ? t.dashboard : t.login}
              <ArrowUpRight size={16} />
            </Button>
            {!user && <Button href="/register" className="header-get-started">{t.getStarted}</Button>}
            <button
              ref={menuButton}
              className="icon-button mobile-menu-button"
              aria-label={open ? tr("Закрыть меню") : tr("Открыть меню")}
              aria-expanded={open}
              aria-controls="mobile-navigation"
              onClick={() => setOpen(!open)}
            >
              {open ? <X /> : <Menu />}
            </button>
          </div>
        </div>
        {open && (
          <nav id="mobile-navigation" className="mobile-nav" aria-label={tr("Основная навигация")}>
            {mobileNavigation(nav, side, !!user, { href: "/login", label: t.login }).map((item) => (
              <Link
                onClick={() => setOpen(false)}
                key={item.href}
                href={item.href}
                aria-current={isActive(item.href) ? "page" : undefined}
              >
                {item.label}
              </Link>
            ))}
          </nav>
        )}
      </header>
      {dashboard ? (
        <div className="workspace">
          <aside className="sidebar">
            <p className="sidebar-label">{tr("Ваше пространство")}</p>
            <nav>
              {side.map(({ href, label, Icon }) => (
                <Link
                  key={href}
                  href={href}
                  className={isActive(href) ? "active" : ""}
                >
                  <Icon size={19} />
                  {label}
                </Link>
              ))}
            </nav>
            <div className="sidebar-profile">
              <CircleUserRound size={26} />
              <div>
                <strong>{user?.full_name || t.dashboard}</strong>
                <small>
                  {user
                    ? tr(statusText(user.role))
                    : tr("Менторство и развитие")}
                </small>
              </div>
            </div>
          </aside>
          <main id="main-content" className="workspace-main">
            {title && (
              <div className="page-heading">
                <p className="eyebrow">{tr("Ваше пространство")}</p>
                <h1>{title}</h1>
                {description && <p className="muted">{description}</p>}
              </div>
            )}
            {children}
          </main>
        </div>
      ) : (
        <main id="main-content">
          {title && (
            <div className="container page-heading">
              <p className="eyebrow">{tr("Сообщество")}</p>
              <h1>{title}</h1>
              {description && <p className="muted">{description}</p>}
            </div>
          )}
          {children}
        </main>
      )}
      <footer className="footer">
        <div className="container footer-inner">
          <div>
            <Link href="/" className="wordmark">
              <BrandLogo secondary /><span className="brand-platform-name">{t.heroEyebrow}</span>
            </Link>
          </div>
          <div>
            <nav>
              {nav.map((item) => (
                <Link key={item.href} href={item.href}>
                  {item.label}
                </Link>
              ))}
            </nav>
            <p>{t.footerNote}</p>
          </div>
        </div>
      </footer>
    </>
  );
}
