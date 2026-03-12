import { useState, useEffect } from 'react';
import { useQuery, useMutation, useQueryClient } from '@tanstack/react-query';
import {
    Zap, Shield, RefreshCw, BarChart3, Activity,
    ChevronLeft, Database, LayoutDashboard, Wallet,
    TrendingUp, Lock, Settings, Layers,
    Unplug, X, Loader2
} from 'lucide-react';
import { fetchPortfolio, fetchPositions, triggerScan, closeTrade, socket, cn } from '../../lib/api';
import ScannerTable from '../scanner/components/ScannerTable';

// ─── Small helpers ────────────────────────────────────

function fmt(v: number, prefix = '$', decimals = 2) {
    const abs = Math.abs(v);
    const str = abs.toLocaleString('en-US', { minimumFractionDigits: decimals, maximumFractionDigits: decimals });
    return `${v < 0 ? '-' : ''}${prefix}${str}`;
}

// ─── Close button with confirmation ──────────────────

function CloseBtn({ groupId, onClose }: { groupId: string; onClose: () => void }) {
    const [confirm, setConfirm] = useState(false);
    const mutation = useMutation({
        mutationFn: () => closeTrade(groupId, 'manual'),
        onSuccess: onClose,
    });

    if (confirm) {
        return (
            <div className="flex items-center gap-1">
                <button onClick={() => mutation.mutate()}
                    disabled={mutation.isPending}
                    className="text-[8px] font-black px-2 py-1 rounded bg-ui-red/20 border border-ui-red/40 text-ui-red hover:bg-ui-red/30 transition-colors flex items-center gap-1">
                    {mutation.isPending ? <Loader2 className="w-2.5 h-2.5 animate-spin" /> : null}
                    CONFIRM
                </button>
                <button onClick={() => setConfirm(false)}
                    className="text-[8px] font-black px-2 py-1 rounded bg-white/5 border border-white/10 text-[#5a6a82] hover:text-white transition-colors">
                    CANCEL
                </button>
            </div>
        );
    }

    return (
        <button onClick={() => setConfirm(true)}
            className="flex items-center gap-1 text-[8px] font-black px-2 py-1 rounded border border-[#151f35] text-[#5a6a82] hover:border-ui-red/40 hover:text-ui-red transition-colors">
            <X className="w-2.5 h-2.5" /> CLOSE
        </button>
    );
}

// ─── Main Page ────────────────────────────────────────

export default function DashboardPage() {
    const queryClient = useQueryClient();
    const [view, setView] = useState('positions');
    const [autoScan, setAutoScan] = useState(false);
    const [isConnected, setIsConnected] = useState(socket.connected);
    const [scanCount, setScanCount] = useState(0);
    const [lastScan, setLastScan] = useState(new Date());

    useEffect(() => {
        socket.on('connect',    () => setIsConnected(true));
        socket.on('disconnect', () => setIsConnected(false));
        socket.on('pairs_update', () => {
            queryClient.invalidateQueries({ queryKey: ['pairs'] });
            setScanCount(c => c + 1);
            setLastScan(new Date());
        });
        socket.on('positions_update', () => {
            queryClient.invalidateQueries({ queryKey: ['portfolio'] });
            queryClient.invalidateQueries({ queryKey: ['positions'] });
        });
        return () => {
            socket.off('connect');
            socket.off('disconnect');
            socket.off('pairs_update');
            socket.off('positions_update');
        };
    }, [queryClient]);

    const { data: portfolio, isError: isPortfolioError } = useQuery({
        queryKey: ['portfolio'],
        queryFn: fetchPortfolio,
        refetchInterval: 30_000,
    });

    const { data: positionsData, isError: isPositionsError } = useQuery({
        queryKey: ['positions'],
        queryFn: fetchPositions,
        refetchInterval: 30_000,
    });

    const scanMutation = useMutation({
        mutationFn: triggerScan,
        onSuccess: () => {
            queryClient.invalidateQueries({ queryKey: ['pairs'] });
            setScanCount(c => c + 1);
            setLastScan(new Date());
        },
    });

    const hasApiControl = isConnected && !isPortfolioError;
    const balance       = portfolio?.balance || {};
    const openPositions: any[] = portfolio?.open_positions || positionsData || [];

    const portfolioStats = [
        { label: "TOTAL EQUITY",   value: hasApiControl ? fmt(balance.total_usdt || 0) : "N/A",            icon: Wallet,    glow: true, color: "text-white",      sub: hasApiControl ? "USDT-M" : "API Required" },
        { label: "AVAILABLE",      value: hasApiControl ? fmt(balance.free_usdt  || 0) : "N/A",            icon: Database,  color: "text-ui-accent" },
        { label: "UNREALIZED P&L", value: hasApiControl ? fmt(portfolio?.unrealized_pnl || 0) : "N/A",    icon: TrendingUp, color: (portfolio?.unrealized_pnl || 0) >= 0 ? "text-ui-green" : "text-ui-red" },
        { label: "REALIZED P&L",   value: hasApiControl ? fmt(portfolio?.realized_pnl  || 0) : "N/A",    icon: Lock,      color: (portfolio?.realized_pnl  || 0) >= 0 ? "text-ui-green" : "text-ui-red" },
        { label: "OPEN PAIRS",     value: hasApiControl ? String(portfolio?.open_pairs  || 0) : "N/A",   icon: Settings,  color: "text-[#c8d6e5]" },
        { label: "WIN RATE",       value: hasApiControl ? `${portfolio?.win_rate || 0}%` : "N/A",         icon: Layers,    color: "text-[#c8d6e5]" },
    ];

    const subStats = [
        { label: "TOTAL TRADES",   value: hasApiControl ? String(portfolio?.total_trades || 0) : "—",    color: "text-white" },
        { label: "WINS",           value: hasApiControl ? String(portfolio?.wins  || 0) : "—",           color: "text-ui-green" },
        { label: "LOSSES",         value: hasApiControl ? String(portfolio?.losses || 0) : "—",          color: "text-ui-red" },
        { label: "TOTAL FEES",     value: hasApiControl ? fmt(portfolio?.total_fees || 0) : "—",         color: "text-[#5a6a82]" },
        { label: "AVG WIN",        value: hasApiControl ? fmt(portfolio?.avg_win   || 0) : "—",          color: "text-ui-green" },
        { label: "AVG LOSS",       value: hasApiControl ? fmt(portfolio?.avg_loss  || 0) : "—",          color: "text-ui-red" },
        { label: "BEST TRADE",     value: hasApiControl ? fmt(portfolio?.best_trade  || 0) : "—",        color: "text-ui-green" },
        { label: "WORST TRADE",    value: hasApiControl ? fmt(portfolio?.worst_trade || 0) : "—",        color: "text-ui-red" },
        { label: "SCAN COUNT",     value: String(scanCount),                                              color: "text-ui-accent" },
        { label: "LAST SCAN",      value: lastScan.toLocaleTimeString(),                                  color: "text-[#5a6a82]" },
    ];

    const tabs = [
        { id: "positions",   label: "POSITIONS" },
        { id: "scanner",     label: "SCANNER" },
        { id: "performance", label: "PERFORMANCE" },
    ];

    return (
        <div className="min-h-screen bg-[#020408] text-[#c8d6e5] font-sans flex flex-col selection:bg-ui-accent/30">

            {/* ═══ TOP NAVIGATION ═══ */}
            <header className="bg-[#05080f] border-b border-[#151f35] sticky top-0 z-50">
                <div className="max-w-[1800px] mx-auto px-6 py-3.5 flex justify-between items-center">
                    <div className="flex items-center gap-4">
                        <button className="flex items-center gap-1.5 text-[10px] font-bold text-[#5a6a82] hover:text-[#c8d6e5] transition-colors uppercase tracking-widest">
                            <ChevronLeft className="w-3.5 h-3.5" />
                            DASHBOARD
                        </button>
                        <div className="w-[1px] h-4 bg-[#151f35]" />
                        <div className="flex items-center gap-2.5">
                            <LayoutDashboard className="w-4 h-4 text-ui-accent" />
                            <span className="text-xs font-black text-white tracking-[0.2em] uppercase">PORTFOLIO</span>
                        </div>
                    </div>

                    <div className="flex items-center gap-6">
                        {/* Auto-scan toggle */}
                        <button
                            onClick={() => setAutoScan(v => !v)}
                            className={cn("flex items-center gap-1.5 px-3 py-1 border rounded-md text-[9px] font-black uppercase tracking-widest transition-colors",
                                autoScan ? "bg-ui-accent/10 border-ui-accent/30 text-ui-accent" : "border-[#151f35] text-[#5a6a82] hover:text-[#c8d6e5]")}>
                            <Zap className="w-3 h-3" />
                            AUTO
                        </button>

                        {/* Manual scan */}
                        <button
                            onClick={() => scanMutation.mutate()}
                            disabled={scanMutation.isPending}
                            className="flex items-center gap-1.5 px-3 py-1 border border-[#151f35] rounded-md text-[9px] font-black uppercase tracking-widest text-[#5a6a82] hover:text-[#c8d6e5] transition-colors disabled:opacity-40">
                            <RefreshCw className={cn("w-3 h-3", scanMutation.isPending && "animate-spin")} />
                            SCAN
                        </button>

                        {/* Connection status */}
                        <div className={cn("flex items-center gap-1.5 px-3 py-1 border rounded-md",
                            isConnected ? "bg-ui-green/5 border-ui-green/20" : "bg-ui-red/5 border-ui-red/20")}>
                            <div className={cn("w-1.5 h-1.5 rounded-full", isConnected ? "bg-ui-green" : "bg-ui-red animate-pulse")} />
                            <span className={cn("text-[9px] font-black uppercase tracking-widest", isConnected ? "text-ui-green" : "text-ui-red")}>
                                {isConnected ? "CONNECTED" : "OFFLINE"}
                            </span>
                        </div>

                        <button onClick={() => queryClient.invalidateQueries()}
                            className="flex items-center gap-2 text-[9px] font-black text-[#5a6a82] hover:text-white transition-colors uppercase tracking-widest">
                            <RefreshCw className="w-3 h-3" />
                            REFRESH
                        </button>
                    </div>
                </div>
            </header>

            <main className="max-w-[1800px] mx-auto w-full p-6 space-y-8 flex-1">

                {/* ═══ MAIN STATS CARDS ═══ */}
                <div className="grid grid-cols-2 md:grid-cols-3 lg:grid-cols-6 gap-4">
                    {portfolioStats.map((stat, idx) => (
                        <div key={idx} className={cn(
                            "stat-card-premium flex flex-col gap-3 relative overflow-hidden group hover:bg-[#0c1425]",
                            stat.glow && hasApiControl && "glow-blue"
                        )}>
                            <div className="flex items-center justify-between">
                                <span className="text-[9px] font-black text-[#5a6a82] tracking-[0.15em] uppercase">{stat.label}</span>
                                <stat.icon className="w-3.5 h-3.5 text-[#5a6a82] opacity-40 group-hover:opacity-100 transition-opacity" />
                            </div>
                            <div className="flex flex-col">
                                <span className={cn("text-xl font-black tracking-tight", stat.color, stat.glow && hasApiControl && "text-glow-blue")}>
                                    {stat.value}
                                </span>
                                {'sub' in stat && (
                                    <span className="text-[7px] font-bold text-[#5a6a82] uppercase tracking-tighter mt-1">{stat.sub}</span>
                                )}
                            </div>
                        </div>
                    ))}
                </div>

                {/* ═══ SUB STATS BAR ═══ */}
                <div className="bg-[#080d18] border border-[#151f35] rounded-xl px-8 py-4 flex items-center justify-between overflow-x-auto gap-8">
                    {subStats.map((s, idx) => (
                        <div key={idx} className="flex flex-col items-center gap-1 min-w-fit">
                            <span className="text-[7px] text-[#5a6a82] font-black tracking-widest uppercase whitespace-nowrap">{s.label}</span>
                            <span className={cn("text-[11px] font-bold tabular-nums", s.color)}>{s.value}</span>
                        </div>
                    ))}
                </div>

                {/* ═══ TABS ═══ */}
                <div className="flex items-center gap-1 border-b border-[#151f35] px-2">
                    {tabs.map((tab) => (
                        <button key={tab.id} onClick={() => setView(tab.id)}
                            className={cn(
                                "px-6 py-3 text-[10px] font-bold tracking-[0.2em] uppercase transition-all relative",
                                view === tab.id
                                    ? "text-ui-accent after:content-[''] after:absolute after:bottom-0 after:left-0 after:right-0 after:h-[2px] after:bg-ui-accent"
                                    : "text-[#5a6a82] hover:text-[#c8d6e5]"
                            )}>
                            <div className="flex items-center gap-2">
                                {tab.id === 'positions' && <BarChart3 className="w-3 h-3" />}
                                {tab.label}
                            </div>
                        </button>
                    ))}
                </div>

                {/* ═══ CONTENT ═══ */}
                <div className="min-h-[500px]">

                    {/* POSITIONS TAB */}
                    {view === 'positions' && (
                        <div className="space-y-6 animate-in fade-in duration-500">
                            <div className="space-y-3">
                                <div className="flex items-center justify-between">
                                    <div className="flex items-center gap-2.5">
                                        <TrendingUp className="w-4 h-4 text-ui-green" />
                                        <h2 className="text-[11px] font-black text-white tracking-[0.15em] uppercase">
                                            OPEN PAIR TRADES ({openPositions.length})
                                        </h2>
                                    </div>
                                    <span className="text-[9px] font-bold text-[#5a6a82] uppercase tracking-[0.1em]">
                                        Live from Binance USDT-M
                                    </span>
                                </div>

                                <div className="bg-[#05080f] border border-[#151f35] rounded-lg overflow-hidden">
                                    {openPositions.length > 0 ? (
                                        <table className="w-full text-left">
                                            <thead>
                                                <tr className="border-b border-[#151f35] bg-[#080d18]/50">
                                                    {["PAIR", "DIRECTION", "SIZE A", "SIZE B", "ENTRY Z", "CURR Z", "CORR", "UPL", "OPENED", "ACTION"].map(h => (
                                                        <th key={h} className="px-4 py-2.5 text-[8px] font-black text-[#5a6a82] tracking-widest uppercase">{h}</th>
                                                    ))}
                                                </tr>
                                            </thead>
                                            <tbody className="divide-y divide-[#151f35]">
                                                {openPositions.map((row: any) => {
                                                    const pnl = row.unrealized_pnl ?? 0;
                                                    return (
                                                        <tr key={row.group_id} className="hover:bg-white/[0.02] transition-colors">
                                                            <td className="px-4 py-3 text-[10px] font-bold text-white whitespace-nowrap">
                                                                {row.symbol_a}/{row.symbol_b}
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <div className="flex gap-1 items-center">
                                                                    <span className={cn("text-[8px] font-black px-1.5 py-0.5 rounded",
                                                                        row.leg_a_side === 'sell' ? "bg-ui-red/10 text-ui-red" : "bg-ui-green/10 text-ui-green")}>
                                                                        {row.leg_a_side === 'sell' ? 'SHORT' : 'LONG'} A
                                                                    </span>
                                                                    <span className={cn("text-[8px] font-black px-1.5 py-0.5 rounded",
                                                                        row.leg_b_side === 'buy' ? "bg-ui-green/10 text-ui-green" : "bg-ui-red/10 text-ui-red")}>
                                                                        {row.leg_b_side === 'buy' ? 'LONG' : 'SHORT'} B
                                                                    </span>
                                                                </div>
                                                            </td>
                                                            <td className="px-4 py-3 text-[10px] tabular-nums text-[#c8d6e5]">${Number(row.size_a_usd).toFixed(0)}</td>
                                                            <td className="px-4 py-3 text-[10px] tabular-nums text-[#c8d6e5]">${Number(row.size_b_usd).toFixed(0)}</td>
                                                            <td className="px-4 py-3 text-[10px] font-bold tabular-nums text-ui-accent">{Number(row.entry_zscore).toFixed(3)}</td>
                                                            <td className="px-4 py-3 text-[10px] font-bold tabular-nums text-ui-accent">{Number(row.current_zscore).toFixed(3)}</td>
                                                            <td className="px-4 py-3 text-[10px] font-bold tabular-nums text-[#c8d6e5]">{Number(row.entry_corr).toFixed(3)}</td>
                                                            <td className={cn("px-4 py-3 text-[10px] font-black tabular-nums", pnl >= 0 ? "text-ui-green" : "text-ui-red")}>
                                                                {fmt(pnl)}
                                                            </td>
                                                            <td className="px-4 py-3 text-[9px] text-[#5a6a82] italic whitespace-nowrap">
                                                                {row.opened_at ? new Date(row.opened_at).toLocaleString() : '—'}
                                                            </td>
                                                            <td className="px-4 py-3">
                                                                <CloseBtn
                                                                    groupId={row.group_id}
                                                                    onClose={() => {
                                                                        queryClient.invalidateQueries({ queryKey: ['portfolio'] });
                                                                        queryClient.invalidateQueries({ queryKey: ['positions'] });
                                                                    }}
                                                                />
                                                            </td>
                                                        </tr>
                                                    );
                                                })}
                                            </tbody>
                                        </table>
                                    ) : (
                                        <div className="p-20 flex flex-col items-center justify-center space-y-3 opacity-30">
                                            {isPositionsError ? <Unplug className="w-8 h-8 text-ui-red" /> : <Layers className="w-8 h-8" />}
                                            <div className="text-center">
                                                <p className="text-[10px] font-black uppercase tracking-widest text-[#c8d6e5]">
                                                    {isPositionsError ? "API BRIDGE OFFLINE" : "NO ACTIVE PAIR TRADES"}
                                                </p>
                                                <p className="text-[8px] font-bold uppercase tracking-widest text-[#5a6a82] mt-1">
                                                    {isPositionsError ? "Check backend connection" : "Scanner will trigger entries when Z-Score ≥ 2.0"}
                                                </p>
                                            </div>
                                        </div>
                                    )}
                                </div>
                            </div>
                        </div>
                    )}

                    {view === 'scanner' && <ScannerTable />}

                    {view === 'performance' && (
                        <div className="bg-[#05080f] border border-[#151f35] rounded-lg p-8">
                            <h2 className="text-[11px] font-black text-white tracking-[0.15em] uppercase mb-6">PERFORMANCE SUMMARY</h2>
                            {hasApiControl ? (
                                <div className="grid grid-cols-2 md:grid-cols-4 gap-6">
                                    {[
                                        { label: "Realized P&L",  val: fmt(portfolio?.realized_pnl || 0),  color: (portfolio?.realized_pnl || 0) >= 0 ? "text-ui-green" : "text-ui-red" },
                                        { label: "Total Fees",    val: fmt(portfolio?.total_fees || 0),     color: "text-[#5a6a82]" },
                                        { label: "Total Trades",  val: String(portfolio?.total_trades || 0), color: "text-white" },
                                        { label: "Win Rate",      val: `${portfolio?.win_rate || 0}%`,      color: "text-ui-green" },
                                        { label: "Avg Win",       val: fmt(portfolio?.avg_win || 0),        color: "text-ui-green" },
                                        { label: "Avg Loss",      val: fmt(portfolio?.avg_loss || 0),       color: "text-ui-red" },
                                        { label: "Best Trade",    val: fmt(portfolio?.best_trade || 0),     color: "text-ui-green" },
                                        { label: "Worst Trade",   val: fmt(portfolio?.worst_trade || 0),    color: "text-ui-red" },
                                    ].map((item, i) => (
                                        <div key={i} className="flex flex-col gap-1 p-4 bg-white/[0.02] rounded-lg border border-[#151f35]">
                                            <span className="text-[8px] text-[#5a6a82] font-black uppercase tracking-widest">{item.label}</span>
                                            <span className={cn("text-lg font-black tabular-nums", item.color)}>{item.val}</span>
                                        </div>
                                    ))}
                                </div>
                            ) : (
                                <div className="flex flex-col items-center justify-center py-20 opacity-30 space-y-3">
                                    <Activity className="w-10 h-10 text-[#5a6a82]" />
                                    <span className="text-[10px] font-black uppercase tracking-widest">API Connection Required</span>
                                </div>
                            )}
                        </div>
                    )}
                </div>
            </main>

            {/* ═══ FOOTER ═══ */}
            <footer className="bg-[#05080f] border-t border-[#151f35] py-3 mt-auto">
                <div className="max-w-[1800px] mx-auto px-6 flex justify-between items-center text-[9px] font-bold text-[#5a6a82] uppercase tracking-wider">
                    <div className="flex items-center gap-6">
                        <span className="text-ui-accent flex items-center gap-2">TRADINGCLAW v3.0</span>
                        <div className="h-3 w-[1px] bg-[#151f35]" />
                        <span className="flex items-center gap-2 italic">
                            <Shield className="h-3 w-3" /> 5-Layer Dedup Active
                        </span>
                    </div>
                    <div className="flex items-center gap-6">
                        <span className="text-ui-orange">Exchange: Binance USDT-M</span>
                        <div className="h-3 w-[1px] bg-[#151f35]" />
                        <span className="text-[#c8d6e5]">Mode: {hasApiControl ? "LIVE" : "DISCONNECTED"}</span>
                        <div className="h-3 w-[1px] bg-[#151f35]" />
                        <span>Sync: <span className={cn(isConnected ? "text-ui-green" : "text-ui-red")}>{isConnected ? "LIVE" : "OFFLINE"}</span></span>
                    </div>
                </div>
            </footer>
        </div>
    );
}
