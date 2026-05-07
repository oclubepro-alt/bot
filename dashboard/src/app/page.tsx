"use client";

import React, { useState, useEffect } from "react";
import { 
  LayoutDashboard, 
  ListChecks, 
  Activity, 
  Settings, 
  CheckCircle2, 
  XCircle, 
  ExternalLink,
  MessageSquare,
  ShieldCheck,
  Zap,
  Globe
} from "lucide-react";

interface Product {
  id: string;
  titulo: string;
  preco: string;
  loja: string;
  link: string;
  imagem?: string;
  created_at: string;
  status: string;
}

interface Health {
  status: string;
  uptime: string;
  scrapers: Record<string, string>;
}

export default function Dashboard() {
  const [queue, setQueue] = useState<Product[]>([]);
  const [health, setHealth] = useState<Health | null>(null);
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    // Mock data for initial preview
    setQueue([
      {
        id: "1",
        titulo: "Smartphone Samsung Galaxy S23 Ultra 5G 256GB",
        preco: "R$ 5.499,00",
        loja: "Amazon",
        link: "https://amazon.com.br/dp/B0BP9M7S9P",
        imagem: "https://m.media-amazon.com/images/I/71XmkoS6vUL._AC_SL1500_.jpg",
        created_at: new Date().toISOString(),
        status: "pending"
      },
      {
        id: "2",
        titulo: "Air Fryer Mondial Family AFN-40-BI 4L",
        preco: "R$ 329,90",
        loja: "Magalu",
        link: "https://magazineluiza.com.br/p/236763400",
        imagem: "https://a-static.mlcdn.com.br/800x560/fritadeira-eletrica-sem-oleo-air-fryer-mondial-family-afn-40-bi-4l-preto/magazineluiza/236763400/21a7c067d5e4939a9c9f0b3e5a5e3a3e.jpg",
        created_at: new Date().toISOString(),
        status: "pending"
      }
    ]);

    setHealth({
      status: "online",
      uptime: "2d 14h",
      scrapers: {
        amazon: "stable",
        shopee: "stable",
        magalu: "stable"
      }
    });
    setLoading(false);
  }, []);

  const approve = (id: string) => {
    setQueue(queue.filter(item => item.id !== id));
  };

  const reject = (id: string) => {
    setQueue(queue.filter(item => item.id !== id));
  };

  return (
    <div className="flex h-screen bg-background text-foreground overflow-hidden">
      {/* Sidebar */}
      <aside className="w-64 sidebar flex flex-col p-4 space-y-8">
        <div className="flex items-center space-x-3 px-2">
          <div className="w-10 h-10 bg-primary rounded-xl flex items-center justify-center shadow-lg shadow-primary/20">
            <Zap className="text-white" size={24} />
          </div>
          <span className="text-xl font-bold tracking-tight">Achadinhos</span>
        </div>

        <nav className="flex-1 space-y-1">
          <button className="flex items-center space-x-3 w-full p-3 bg-primary/10 text-primary rounded-lg font-medium transition-all">
            <LayoutDashboard size={20} />
            <span>Mission Control</span>
          </button>
          <button className="flex items-center space-x-3 w-full p-3 text-foreground/60 hover:bg-surface-high hover:text-foreground rounded-lg transition-all">
            <ListChecks size={20} />
            <span>Fila de Aprovação</span>
          </button>
          <button className="flex items-center space-x-3 w-full p-3 text-foreground/60 hover:bg-surface-high hover:text-foreground rounded-lg transition-all">
            <Activity size={20} />
            <span>Status Scrapers</span>
          </button>
          <button className="flex items-center space-x-3 w-full p-3 text-foreground/60 hover:bg-surface-high hover:text-foreground rounded-lg transition-all">
            <Settings size={20} />
            <span>Configurações</span>
          </button>
        </nav>

        <div className="p-4 bg-surface rounded-xl border border-outline/30">
          <div className="flex items-center justify-between mb-2">
            <span className="text-xs text-foreground/50 font-medium uppercase tracking-wider">Bot Status</span>
            <div className="w-2 h-2 bg-green-500 rounded-full animate-pulse-fast shadow-[0_0_8px_#22c55e]" />
          </div>
          <div className="text-sm font-semibold">{health?.uptime} uptime</div>
        </div>
      </aside>

      {/* Main Content */}
      <main className="flex-1 flex flex-col overflow-hidden">
        <header className="h-16 border-b border-outline/20 flex items-center justify-between px-8 bg-background/50 backdrop-blur-sm z-10">
          <h1 className="text-lg font-semibold flex items-center gap-2">
            <MessageSquare size={18} className="text-primary" />
            Mission Control
          </h1>
          <div className="flex items-center space-x-4">
            <div className="flex -space-x-2">
              <div className="w-8 h-8 rounded-full border-2 border-background bg-surface-high flex items-center justify-center text-[10px] font-bold">AZ</div>
              <div className="w-8 h-8 rounded-full border-2 border-background bg-primary flex items-center justify-center text-[10px] font-bold text-white">SP</div>
              <div className="w-8 h-8 rounded-full border-2 border-background bg-orange-500 flex items-center justify-center text-[10px] font-bold text-white">ML</div>
            </div>
            <button className="bg-surface-high px-4 py-2 rounded-lg text-sm font-medium hover:bg-outline/20 transition-all border border-outline/30">
              Refresh Data
            </button>
          </div>
        </header>

        <div className="flex-1 overflow-y-auto p-8 grid grid-cols-1 lg:grid-cols-2 gap-8">
          {/* Approval Queue */}
          <section className="space-y-6">
            <div className="flex items-center justify-between">
              <h2 className="text-xl font-bold flex items-center gap-2">
                <ListChecks className="text-primary" />
                Fila de Aprovação
                <span className="ml-2 text-xs bg-primary/20 text-primary px-2 py-0.5 rounded-full">{queue.length} pendentes</span>
              </h2>
            </div>

            <div className="space-y-4">
              {queue.map(item => (
                <div key={item.id} className="bg-surface rounded-2xl border border-outline/30 overflow-hidden hover:border-primary/50 transition-all shadow-xl group">
                  <div className="p-4 flex gap-4">
                    <div className="w-32 h-32 bg-white rounded-xl overflow-hidden flex-shrink-0 border border-outline/20">
                      <img src={item.imagem} alt={item.titulo} className="w-full h-full object-contain" />
                    </div>
                    <div className="flex-1 flex flex-col justify-between py-1">
                      <div>
                        <div className="flex items-center justify-between mb-1">
                          <span className="text-[10px] font-bold uppercase tracking-widest text-primary bg-primary/10 px-2 py-0.5 rounded">{item.loja}</span>
                          <span className="text-[10px] text-foreground/40">{new Date(item.created_at).toLocaleTimeString()}</span>
                        </div>
                        <h3 className="text-sm font-semibold leading-tight line-clamp-2 mb-2 group-hover:text-primary transition-colors">{item.titulo}</h3>
                        <div className="text-lg font-bold text-foreground">{item.preco}</div>
                      </div>
                      <div className="flex items-center gap-2 pt-3">
                        <button 
                          onClick={() => approve(item.id)}
                          className="flex-1 bg-primary text-white py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-2 hover:bg-primary/80 transition-all shadow-lg shadow-primary/20"
                        >
                          <CheckCircle2 size={14} /> Aprovar
                        </button>
                        <button 
                          onClick={() => reject(item.id)}
                          className="flex-1 bg-surface-high text-foreground py-2 rounded-lg text-xs font-bold flex items-center justify-center gap-2 hover:bg-red-500/10 hover:text-red-500 transition-all border border-outline/30"
                        >
                          <XCircle size={14} /> Rejeitar
                        </button>
                      </div>
                    </div>
                  </div>
                </div>
              ))}
              {queue.length === 0 && (
                <div className="h-64 flex flex-col items-center justify-center text-foreground/30 border-2 border-dashed border-outline/20 rounded-2xl">
                  <ShieldCheck size={48} className="mb-4 opacity-20" />
                  <p>Fila vazia. Bom trabalho!</p>
                </div>
              )}
            </div>
          </section>

          {/* Telegram Mirror Preview */}
          <section className="space-y-6">
            <h2 className="text-xl font-bold flex items-center gap-2">
              <Globe className="text-primary" />
              Telegram Live Mirror
            </h2>
            
            <div className="bg-[#0e1621] rounded-2xl h-[calc(100vh-16rem)] border border-outline/30 flex flex-col overflow-hidden relative shadow-2xl">
              <div className="bg-[#17212b] p-3 border-b border-black/20 flex items-center gap-3">
                <div className="w-8 h-8 bg-primary rounded-full flex items-center justify-center text-white text-xs font-bold">BA</div>
                <div>
                  <div className="text-xs font-bold">Achadinhos do Dia 💎</div>
                  <div className="text-[10px] text-primary">online</div>
                </div>
              </div>
              
              <div className="flex-1 p-6 space-y-6 overflow-y-auto pattern-bg">
                {/* Sample Message */}
                <div className="tg-bubble ml-auto">
                  <div className="text-[13px] font-bold text-primary mb-1">Achadinhos Bot</div>
                  <div className="bg-white rounded-lg mb-2 overflow-hidden border border-black/10">
                    <img src={queue[0]?.imagem || "https://m.media-amazon.com/images/I/71XmkoS6vUL._AC_SL1500_.jpg"} alt="preview" className="w-full h-48 object-contain" />
                  </div>
                  <div className="text-sm leading-relaxed whitespace-pre-wrap">
                    🔥 <b>{queue[0]?.titulo || "Smartphone Samsung Galaxy S23 Ultra"}</b>{"\n\n"}
                    💰 Por apenas <b>{queue[0]?.preco || "R$ 5.499,00"}</b>{"\n\n"}
                    👉 <span className="tg-link">Clique aqui para comprar</span>{"\n\n"}
                    ⚡ <i>Oferta por tempo limitado. Corra!</i>
                  </div>
                  <div className="flex justify-end items-center gap-1 mt-1">
                    <span className="text-[10px] text-[#708499]">14:52</span>
                    <CheckCircle2 size={10} className="text-primary" />
                  </div>
                </div>

                <div className="flex justify-center">
                  <span className="bg-[#1c2733] px-3 py-1 rounded-full text-[10px] font-medium text-foreground/50">HOJE</span>
                </div>

                <div className="tg-bubble ml-auto">
                  <div className="text-sm leading-relaxed">
                    Bem-vindo ao Mission Control! Aqui você verá as ofertas conforme elas forem aprovadas.
                  </div>
                  <div className="flex justify-end items-center gap-1 mt-1">
                    <span className="text-[10px] text-[#708499]">10:05</span>
                    <CheckCircle2 size={10} className="text-primary" />
                  </div>
                </div>
              </div>

              {/* Input Area (Mock) */}
              <div className="p-3 bg-[#17212b] border-t border-black/20 flex items-center gap-3">
                <div className="flex-1 bg-[#0e1621] rounded-lg px-4 py-2 text-xs text-foreground/40 border border-outline/10">
                  Visualização em tempo real...
                </div>
                <div className="w-8 h-8 bg-primary rounded-full flex items-center justify-center text-white">
                  <Zap size={16} />
                </div>
              </div>
            </div>
          </section>
        </div>
      </main>
    </div>
  );
}
