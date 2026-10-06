import type { Metadata } from "next";
import { Noto_Sans, Poppins } from "next/font/google";
import { LocaleProvider } from "@/lib/i18n";
import { PlatformProvider } from "@/components/platform-status";
import "./globals.css";
import "./wit-home.css";
import "./wit-shell.css";
import "./mentor-discovery.css";
import "./community-design.css";
const noto = Noto_Sans({
  subsets: ["cyrillic", "cyrillic-ext", "latin"],
  variable: "--font-noto",
  display: "swap",
});
const poppins = Poppins({
  subsets: ["latin"],
  weight: ["400", "600", "700"],
  variable: "--font-poppins",
  display: "swap",
});
export const metadata: Metadata = {
  title: {
    default: "Менторская платформа Women in Tech Kazakhstan",
    template: "%s · Women in Tech Kazakhstan",
  },
  description:
    "Найдите ментора, присоединитесь к проекту или предложите собственную идею. Women in Tech Kazakhstan объединяет участников и экспертов и помогает достигать измеримых результатов.",
};
export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="ru" className={`${noto.variable} ${poppins.variable}`}>
      <body>
        <LocaleProvider>
          <PlatformProvider>{children}</PlatformProvider>
        </LocaleProvider>
      </body>
    </html>
  );
}
