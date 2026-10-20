import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "Quant Office AI — Centro de Comando 2D & Fundo Quantitativo",
  description:
    "Escritório virtual gamificado 2D e terminal de inteligência quantitativa com monitoramento em tempo real via Supabase Realtime.",
};

export default function RootLayout({
  children,
}: {
  children: React.ReactNode;
}) {
  return (
    <html lang="pt-BR" className="dark h-full antialiased bg-[#05070c]">
      <body className="min-h-full flex flex-col bg-[#05070c] text-slate-100 selection:bg-cyan-500/30 selection:text-cyan-200">
        {children}
      </body>
    </html>
  );
}
