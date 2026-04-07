import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Job_Seekr",
  description: "AI-powered job application pipeline",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="en">
      <body className="min-h-screen bg-gray-950 text-gray-100 font-mono">
        <nav className="border-b border-gray-800 px-6 py-3 flex items-center gap-6">
          <span className="text-white font-bold text-lg tracking-tight">Job_Seekr</span>
          <a href="/" className="text-sm text-gray-400 hover:text-white transition-colors">
            Triage Board
          </a>
          <a href="/upload" className="text-sm text-gray-400 hover:text-white transition-colors">
            Upload Resume
          </a>
        </nav>
        <main className="px-6 py-8">{children}</main>
      </body>
    </html>
  );
}
