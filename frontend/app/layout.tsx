import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Text-to-SQL Oracle SAC",
  description: "Frontend MVP for the governed Text-to-SQL Oracle SAC backend"
};

export default function RootLayout({
  children
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="es">
      <body>{children}</body>
    </html>
  );
}
