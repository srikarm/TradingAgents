import type { ReactNode } from "react";
import { Inter, JetBrains_Mono } from "next/font/google";
import SessionProviderClient from "@/components/SessionProviderClient";
import "./globals.css";

// Inter for UI, JetBrains Mono for prices, tickers, log streams. CSS variables
// so Tailwind's font-sans / font-mono utilities resolve to these without a
// global preflight rewrite.
const inter = Inter({
  subsets: ["latin"],
  variable: "--font-inter",
  display: "swap",
});

const jetbrainsMono = JetBrains_Mono({
  subsets: ["latin"],
  variable: "--font-jetbrains-mono",
  display: "swap",
});

export const metadata = {
  title: "TradingAgents Dashboard",
  description: "Multi-agent LLM trading framework — run analyses, watch reasoning, track P&L.",
};

export const viewport = {
  themeColor: "#080808", // Axiara Background
};

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en" className={`${inter.variable} ${jetbrainsMono.variable} dark`}>
      <body className="bg-bg text-fg">
        <SessionProviderClient>{children}</SessionProviderClient>
      </body>
    </html>
  );
}
