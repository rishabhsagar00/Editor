import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "RowInsert — statement row editor",
  description: "Upload a statement image/PDF, detect rows, insert a new row.",
};

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>{children}</body>
    </html>
  );
}
