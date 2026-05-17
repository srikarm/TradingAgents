import type { ReactNode } from "react";
import SessionProviderClient from "@/components/SessionProviderClient";

export const metadata = { title: "TradingAgents Dashboard" };

export default function RootLayout({ children }: { children: ReactNode }) {
  return (
    <html lang="en">
      <body style={{ fontFamily: "system-ui, sans-serif", margin: 0 }}>
        <SessionProviderClient>{children}</SessionProviderClient>
      </body>
    </html>
  );
}
