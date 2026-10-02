import type { Metadata } from "next";
import { Noto_Sans, Poppins } from "next/font/google";
import { LocaleProvider } from "@/lib/i18n";
import { PlatformProvider } from "@/components/platform-status";
import "./globals.css";
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
    default: "DanaConnect — менторство и развитие",
    template: "%s · DanaConnect",
  },
  description:
    "Платформа менторства: найдите ментора, развивайте проект и планируйте встречи.",
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
