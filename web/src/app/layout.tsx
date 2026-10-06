import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "CVP Contable",
  description: "Conciliación de estados de cuenta — uso interno",
  robots: { index: false, follow: false },
};

export default function RootLayout({ children }: LayoutProps<"/">) {
  return (
    <html lang="es" className="h-full antialiased">
      <body className="flex min-h-full flex-col">{children}</body>
    </html>
  );
}
