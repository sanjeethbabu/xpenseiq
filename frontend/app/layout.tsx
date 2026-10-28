import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "XpenzIQ — Your expense expert",
  description: "Turn financial documents into financial intelligence.",
  icons: {
    icon: "/sole_logo.png",
    shortcut: "/sole_logo.png",
    apple: "/sole_logo.png",
  },
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
