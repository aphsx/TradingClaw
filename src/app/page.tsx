"use client";

import {
  Activity,
  ArrowLeftRight,
  Check,
  CircleDollarSign,
  ClipboardList,
  Copy,
  Gamepad2,
  Menu,
  Plus,
  RotateCcw,
  Search,
  ShieldCheck,
  Trash2,
  Trophy,
  Wallet,
  X,
  Zap,
} from "lucide-react";
import { useMemo, useState } from "react";

type Outcome = "left" | "draw" | "right";
type BetStatus = "pending" | "won" | "lost" | "void";
type ActiveTab = "create" | "records";
type Filter = "all" | BetStatus;

type BetRecord = {
  id: string;
  sport: string;
  teamLeft: string;
  teamRight: string;
  hasDraw: boolean;
  oddsLeft: string;
  oddsDraw: string;
  oddsRight: string;
  selectedOutcome: Outcome;
  stake: string;
  status: BetStatus;
  createdAt: string;
};

type BetFormState = Omit<BetRecord, "id" | "status" | "createdAt">;

const sports = ["บอล", "บาส", "มวย", "eSports", "อื่น ๆ"];

const statusConfig: Record<
  BetStatus,
  { label: string; className: string; icon: React.ReactNode }
> = {
  pending: {
    label: "รอผล",
    className: "border-blue-400/40 bg-blue-400/15 text-blue-100",
    icon: <RotateCcw className="h-4 w-4" />,
  },
  won: {
    label: "ชนะ",
    className: "border-sky-400/40 bg-sky-400/15 text-sky-100",
    icon: <Check className="h-4 w-4" />,
  },
  lost: {
    label: "แพ้",
    className: "border-rose-400/40 bg-rose-400/15 text-rose-100",
    icon: <X className="h-4 w-4" />,
  },
  void: {
    label: "คืนทุน",
    className: "border-slate-400/40 bg-slate-400/15 text-slate-100",
    icon: <Wallet className="h-4 w-4" />,
  },
};

const initialForm: BetFormState = {
  sport: "บอล",
  teamLeft: "",
  teamRight: "",
  hasDraw: true,
  oddsLeft: "",
  oddsDraw: "",
  oddsRight: "",
  selectedOutcome: "left",
  stake: "",
};

const starterRecords: BetRecord[] = [
  {
    id: "sample-1",
    sport: "บอล",
    teamLeft: "Arsenal",
    teamRight: "Chelsea",
    hasDraw: true,
    oddsLeft: "0.82",
    oddsDraw: "2.75",
    oddsRight: "1.05",
    selectedOutcome: "left",
    stake: "1000",
    status: "pending",
    createdAt: "วันนี้ 19:20",
  },
  {
    id: "sample-2",
    sport: "eSports",
    teamLeft: "Talon",
    teamRight: "Secret",
    hasDraw: false,
    oddsLeft: "0.95",
    oddsDraw: "",
    oddsRight: "0.88",
    selectedOutcome: "right",
    stake: "500",
    status: "won",
    createdAt: "วันนี้ 18:10",
  },
];

function money(value: number) {
  return new Intl.NumberFormat("th-TH", {
    maximumFractionDigits: 0,
  }).format(value);
}

function getOutcomeLabel(record: Pick<BetRecord, "selectedOutcome" | "teamLeft" | "teamRight">) {
  if (record.selectedOutcome === "left") return record.teamLeft || "ทีมซ้าย";
  if (record.selectedOutcome === "right") return record.teamRight || "ทีมขวา";
  return "เสมอ";
}

function getSelectedOdds(record: Pick<BetRecord, "selectedOutcome" | "oddsLeft" | "oddsDraw" | "oddsRight">) {
  if (record.selectedOutcome === "left") return Number(record.oddsLeft || 0);
  if (record.selectedOutcome === "right") return Number(record.oddsRight || 0);
  return Number(record.oddsDraw || 0);
}

function getProjectedProfit(record: Pick<BetRecord, "stake" | "selectedOutcome" | "oddsLeft" | "oddsDraw" | "oddsRight">) {
  return Number(record.stake || 0) * getSelectedOdds(record);
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("create");
  const [filter, setFilter] = useState<Filter>("all");
  const [records, setRecords] = useState<BetRecord[]>(starterRecords);
  const [form, setForm] = useState<BetFormState>(initialForm);
  const [lastStake, setLastStake] = useState("1000");

  const canSave =
    form.teamLeft.trim() &&
    form.teamRight.trim() &&
    form.stake.trim() &&
    (form.selectedOutcome !== "draw" || form.hasDraw);

  const filteredRecords = useMemo(() => {
    if (filter === "all") return records;
    return records.filter((record) => record.status === filter);
  }, [filter, records]);

  const summary = useMemo(() => {
    return records.reduce(
      (acc, record) => {
        const stake = Number(record.stake || 0);
        const profit = getProjectedProfit(record);

        acc.totalStake += stake;
        if (record.status === "won") acc.net += profit;
        if (record.status === "lost") acc.net -= stake;
        if (record.status === "pending") acc.pending += stake;
        return acc;
      },
      { totalStake: 0, net: 0, pending: 0 },
    );
  }, [records]);

  function updateForm(key: keyof BetFormState, value: string | boolean) {
    setForm((current) => ({ ...current, [key]: value }));
  }

  function saveRecord() {
    if (!canSave) return;

    const nextRecord: BetRecord = {
      ...form,
      id: crypto.randomUUID(),
      status: "pending",
      createdAt: new Intl.DateTimeFormat("th-TH", {
        hour: "2-digit",
        minute: "2-digit",
      }).format(new Date()),
    };

    setRecords((current) => [nextRecord, ...current]);
    setLastStake(form.stake);
    setForm({
      ...initialForm,
      sport: form.sport,
      stake: form.stake,
      hasDraw: form.hasDraw,
    });
  }

  function setRecordStatus(id: string, status: BetStatus) {
    setRecords((current) =>
      current.map((record) => (record.id === id ? { ...record, status } : record)),
    );
  }

  function copyRecord(record: BetRecord) {
    setForm({
      sport: record.sport,
      teamLeft: record.teamLeft,
      teamRight: record.teamRight,
      hasDraw: record.hasDraw,
      oddsLeft: record.oddsLeft,
      oddsDraw: record.oddsDraw,
      oddsRight: record.oddsRight,
      selectedOutcome: record.selectedOutcome,
      stake: record.stake,
    });
    setActiveTab("create");
  }

  function deleteRecord(id: string) {
    setRecords((current) => current.filter((record) => record.id !== id));
  }

  function swapTeams() {
    setForm((current) => ({
      ...current,
      teamLeft: current.teamRight,
      teamRight: current.teamLeft,
      oddsLeft: current.oddsRight,
      oddsRight: current.oddsLeft,
      selectedOutcome:
        current.selectedOutcome === "left"
          ? "right"
          : current.selectedOutcome === "right"
            ? "left"
            : "draw",
    }));
  }

  const latestRecord = records[0];

  return (
    <main className="min-h-screen text-slate-50">
      <div className="mx-auto grid min-h-screen w-full max-w-[1440px] gap-4 px-3 py-3 lg:grid-cols-[232px_1fr]">
        <aside className="hidden rounded-3xl border border-white/10 bg-[#0b1320]/90 p-3 shadow-2xl shadow-black/30 lg:block">
          <div className="flex items-center gap-3 rounded-2xl bg-slate-950/80 p-3">
            <div className="grid h-10 w-10 place-items-center rounded-2xl bg-sky-400 text-slate-950 shadow-lg shadow-sky-500/25">
              <Zap className="h-5 w-5 fill-current" />
            </div>
            <div>
              <p className="text-lg font-black leading-none">Thunderpick</p>
              <p className="mt-1 text-xs font-semibold text-slate-400">manual bet log</p>
            </div>
          </div>

          <div className="mt-4 space-y-1">
            <SideNavItem active icon={<Activity className="h-4 w-4" />} label="Sportsbook" />
            <SideNavItem icon={<Gamepad2 className="h-4 w-4" />} label="Esports" />
            <SideNavItem icon={<CircleDollarSign className="h-4 w-4" />} label="Casino" />
            <SideNavItem icon={<ShieldCheck className="h-4 w-4" />} label="My Bets" />
          </div>

          <div className="mt-5 rounded-2xl border border-sky-400/15 bg-sky-400/10 p-4">
            <p className="text-xs font-bold uppercase tracking-[0.24em] text-sky-200/70">Quick Stats</p>
            <div className="mt-3 space-y-3">
              <SummaryStat label="ลงทั้งหมด" value={money(summary.totalStake)} />
              <SummaryStat label="ค้างผล" value={money(summary.pending)} />
              <SummaryStat
                highlight={summary.net >= 0}
                label="กำไรสุทธิ"
                value={`${summary.net >= 0 ? "+" : ""}${money(summary.net)}`}
              />
            </div>
          </div>
        </aside>

        <section className="flex min-w-0 flex-col gap-4">
          <header className="sticky top-3 z-30 flex items-center gap-3 rounded-3xl border border-white/10 bg-[#0b1320]/90 p-3 shadow-2xl shadow-black/30 backdrop-blur">
            <button className="grid h-11 w-11 place-items-center rounded-2xl border border-white/10 bg-slate-900/80 lg:hidden" type="button">
              <Menu className="h-5 w-5" />
            </button>
            <div className="hidden items-center gap-2 rounded-2xl bg-slate-950/70 px-3 py-2 text-sm font-black sm:flex lg:hidden">
              <Zap className="h-4 w-4 fill-sky-300 text-sky-300" />
              Thunderpick
            </div>
            <div className="flex min-w-0 flex-1 items-center gap-2 rounded-2xl border border-white/10 bg-slate-950/70 px-3 py-3 text-slate-400">
              <Search className="h-4 w-4 shrink-0" />
              <span className="truncate text-sm">ค้นหาทีม ลีก หรือรายการที่จดไว้</span>
            </div>
            <button
              className="rounded-2xl bg-sky-400 px-4 py-3 text-sm font-black text-slate-950 shadow-lg shadow-sky-500/20"
              onClick={() => setActiveTab("create")}
              type="button"
            >
              ลงพนัน
            </button>
          </header>

          <div className="grid gap-4 xl:grid-cols-[1fr_360px]">
            <div className="min-w-0 space-y-4">
              <section className="overflow-hidden rounded-3xl border border-sky-400/15 bg-slate-950/75 shadow-2xl shadow-black/30">
                <div className="border-b border-white/10 bg-[linear-gradient(135deg,rgba(14,165,233,0.22),rgba(15,23,42,0.45))] p-5">
                  <div className="flex flex-col gap-4 sm:flex-row sm:items-end sm:justify-between">
                    <div>
                      <div className="inline-flex items-center gap-2 rounded-full border border-sky-400/25 bg-sky-400/10 px-3 py-1 text-xs font-black text-sky-100">
                        <Zap className="h-3.5 w-3.5 fill-sky-300 text-sky-300" />
                        Lightning fast record
                      </div>
                      <h1 className="mt-3 text-3xl font-black tracking-tight">Sportsbook Slip</h1>
                      <p className="mt-2 max-w-xl text-sm text-slate-300">
                        กรอกคู่แข่งเองแบบเร็ว แล้วเลือก odds เหมือน market บนเว็บเดิมพัน
                      </p>
                    </div>
                    <div className="grid grid-cols-3 gap-2 rounded-2xl bg-slate-950/55 p-2">
                      <SummaryStat label="ลงทั้งหมด" value={money(summary.totalStake)} />
                      <SummaryStat label="รอผล" value={money(summary.pending)} />
                      <SummaryStat
                        highlight={summary.net >= 0}
                        label="สุทธิ"
                        value={`${summary.net >= 0 ? "+" : ""}${money(summary.net)}`}
                      />
                    </div>
                  </div>
                </div>

                <div className="grid grid-cols-2 gap-2 border-b border-white/10 bg-slate-900/45 p-2 sm:flex">
                  <TabButton
                    active={activeTab === "create"}
                    icon={<Plus className="h-5 w-5" />}
                    label="ลงพนัน"
                    onClick={() => setActiveTab("create")}
                  />
                  <TabButton
                    active={activeTab === "records"}
                    icon={<ClipboardList className="h-5 w-5" />}
                    label={`รายการ (${records.length})`}
                    onClick={() => setActiveTab("records")}
                  />
                </div>

                {activeTab === "create" ? (
                  <div className="p-4 sm:p-5">
                    <div className="mb-4 flex flex-wrap items-center justify-between gap-3">
                      <div>
                        <p className="text-xs font-black uppercase tracking-[0.24em] text-sky-200/70">Market Builder</p>
                        <h2 className="mt-1 text-xl font-black">สร้างคู่แข่งขัน</h2>
                      </div>
                      <button
                        className="inline-flex items-center gap-2 rounded-xl border border-white/10 bg-slate-900/70 px-3 py-2 text-sm font-bold text-slate-200 transition hover:bg-sky-400/10"
                        onClick={swapTeams}
                        type="button"
                      >
                        <ArrowLeftRight className="h-4 w-4" />
                        สลับทีม
                      </button>
                    </div>

                    <div className="mb-4 flex gap-2 overflow-x-auto pb-1">
                      {sports.map((sport) => (
                        <button
                          className={`shrink-0 rounded-xl border px-4 py-2 text-sm font-black transition ${
                            form.sport === sport
                              ? "border-sky-300 bg-sky-400 text-slate-950 shadow-lg shadow-sky-500/20"
                              : "border-white/10 bg-slate-900/70 text-slate-300 hover:bg-sky-400/10"
                          }`}
                          key={sport}
                          onClick={() => updateForm("sport", sport)}
                          type="button"
                        >
                          {sport}
                        </button>
                      ))}
                    </div>

                    <div className="rounded-2xl border border-white/10 bg-slate-900/45 p-3">
                      <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
                        <TextField
                          label="ทีมซ้าย"
                          onChange={(value) => updateForm("teamLeft", value)}
                          placeholder="เช่น Arsenal"
                          value={form.teamLeft}
                        />
                        <div className="hidden pb-4 text-center text-xs font-black text-slate-500 sm:block">MATCH</div>
                        <TextField
                          label="ทีมขวา"
                          onChange={(value) => updateForm("teamRight", value)}
                          placeholder="เช่น Chelsea"
                          value={form.teamRight}
                        />
                      </div>

                      <div className="mt-4 grid gap-3 sm:grid-cols-3">
                        <TextField
                          label={`น้ำ ${form.teamLeft || "ทีมซ้าย"}`}
                          onChange={(value) => updateForm("oddsLeft", value)}
                          placeholder="0.85"
                          type="number"
                          value={form.oddsLeft}
                        />
                        <div className={form.hasDraw ? "block" : "hidden sm:block"}>
                          <TextField
                            disabled={!form.hasDraw}
                            label="น้ำเสมอ"
                            onChange={(value) => updateForm("oddsDraw", value)}
                            placeholder="2.50"
                            type="number"
                            value={form.oddsDraw}
                          />
                        </div>
                        <TextField
                          label={`น้ำ ${form.teamRight || "ทีมขวา"}`}
                          onChange={(value) => updateForm("oddsRight", value)}
                          placeholder="0.95"
                          type="number"
                          value={form.oddsRight}
                        />
                      </div>
                    </div>

                    <div className="mt-4 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-white/10 bg-slate-900/45 p-3">
                      <div>
                        <p className="font-black">ตลาด 1X2</p>
                        <p className="text-xs text-slate-400">เปิดเสมอเมื่อรายการนี้มีราคา X</p>
                      </div>
                      <button
                        className={`rounded-xl px-4 py-2 text-sm font-black transition ${
                          form.hasDraw ? "bg-sky-400 text-slate-950" : "bg-slate-800 text-slate-200"
                        }`}
                        onClick={() => updateForm("hasDraw", !form.hasDraw)}
                        type="button"
                      >
                        {form.hasDraw ? "มีเสมอ" : "ไม่มีเสมอ"}
                      </button>
                    </div>

                    <div className="mt-4 rounded-2xl border border-white/10 bg-[#0d1726] p-3">
                      <div className="mb-3 flex items-center justify-between">
                        <p className="text-sm font-black text-slate-200">Match Winner</p>
                        <p className="text-xs font-bold text-slate-500">เลือก odds ที่ลง</p>
                      </div>
                      <div className={`grid gap-2 ${form.hasDraw ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
                        <OutcomeButton
                          active={form.selectedOutcome === "left"}
                          label={form.teamLeft || "ทีมซ้าย"}
                          odds={form.oddsLeft}
                          onClick={() => updateForm("selectedOutcome", "left")}
                        />
                        {form.hasDraw ? (
                          <OutcomeButton
                            active={form.selectedOutcome === "draw"}
                            label="เสมอ"
                            odds={form.oddsDraw}
                            onClick={() => updateForm("selectedOutcome", "draw")}
                          />
                        ) : null}
                        <OutcomeButton
                          active={form.selectedOutcome === "right"}
                          label={form.teamRight || "ทีมขวา"}
                          odds={form.oddsRight}
                          onClick={() => updateForm("selectedOutcome", "right")}
                        />
                      </div>
                    </div>

                    <div className="mt-4 grid gap-3 sm:grid-cols-[1fr_auto]">
                      <TextField
                        label="จำนวนเงิน"
                        onChange={(value) => updateForm("stake", value)}
                        placeholder="1000"
                        type="number"
                        value={form.stake}
                      />
                      <button
                        className="self-end rounded-xl border border-white/10 bg-slate-900/70 px-4 py-3 text-sm font-black text-slate-200 transition hover:bg-sky-400/10"
                        onClick={() => updateForm("stake", lastStake)}
                        type="button"
                      >
                        ใช้เงินล่าสุด {money(Number(lastStake || 0))}
                      </button>
                    </div>

                    <button
                      className="mt-4 w-full rounded-2xl bg-sky-400 px-5 py-4 text-base font-black text-slate-950 shadow-xl shadow-sky-950/35 transition hover:bg-sky-300 disabled:cursor-not-allowed disabled:opacity-40"
                      disabled={!canSave}
                      onClick={saveRecord}
                      type="button"
                    >
                      Add to Bet Slip
                    </button>
                  </div>
                ) : (
                  <div className="grid gap-4 p-4 sm:p-5 lg:grid-cols-[280px_1fr]">
                    <aside className="rounded-2xl border border-white/10 bg-slate-900/45 p-3">
                      <h2 className="text-lg font-black">My Bets</h2>
                      <p className="mt-1 text-sm text-slate-400">ดูภาพรวมและตัดผลรายการที่ลงแล้ว</p>

                      <div className="mt-4 grid gap-2">
                        <InfoTile icon={<Wallet className="h-5 w-5" />} label="เงินที่ลงทั้งหมด" value={money(summary.totalStake)} />
                        <InfoTile icon={<RotateCcw className="h-5 w-5" />} label="รอผล" value={money(summary.pending)} />
                        <InfoTile
                          icon={<Trophy className="h-5 w-5" />}
                          label="กำไรสุทธิ"
                          positive={summary.net >= 0}
                          value={`${summary.net >= 0 ? "+" : ""}${money(summary.net)}`}
                        />
                      </div>

                      <div className="mt-4">
                        <p className="mb-2 text-sm font-black text-slate-200">กรองสถานะ</p>
                        <div className="grid grid-cols-2 gap-2">
                          <FilterButton active={filter === "all"} label="ทั้งหมด" onClick={() => setFilter("all")} />
                          {(Object.keys(statusConfig) as BetStatus[]).map((status) => (
                            <FilterButton
                              active={filter === status}
                              key={status}
                              label={statusConfig[status].label}
                              onClick={() => setFilter(status)}
                            />
                          ))}
                        </div>
                      </div>
                    </aside>

                    <div className="space-y-3">
                      {filteredRecords.length ? (
                        filteredRecords.map((record) => (
                          <BetCard
                            key={record.id}
                            onCopy={() => copyRecord(record)}
                            onDelete={() => deleteRecord(record.id)}
                            onStatusChange={(status) => setRecordStatus(record.id, status)}
                            record={record}
                          />
                        ))
                      ) : (
                        <div className="rounded-2xl border border-dashed border-sky-400/15 bg-sky-400/[0.04] p-8 text-center text-slate-300/75">
                          ยังไม่มีรายการในตัวกรองนี้
                        </div>
                      )}
                    </div>
                  </div>
                )}
              </section>
            </div>

            <aside className="space-y-4 xl:sticky xl:top-24 xl:h-fit">
              <section className="rounded-3xl border border-white/10 bg-[#0b1320]/90 p-4 shadow-2xl shadow-black/30">
                <div className="mb-4 flex items-center justify-between">
                  <div>
                    <p className="text-xs font-black uppercase tracking-[0.22em] text-sky-200/70">Bet Slip</p>
                    <h2 className="mt-1 text-xl font-black">Preview</h2>
                  </div>
                  <span className="rounded-xl bg-sky-400/15 px-3 py-1 text-xs font-black text-sky-100">
                    Single
                  </span>
                </div>

                <BetCard
                  onCopy={() => undefined}
                  onDelete={() => undefined}
                  onStatusChange={() => undefined}
                  preview
                  record={{
                    ...form,
                    id: "preview",
                    status: "pending",
                    createdAt: "ตอนนี้",
                    teamLeft: form.teamLeft || "ทีมซ้าย",
                    teamRight: form.teamRight || "ทีมขวา",
                    stake: form.stake || "0",
                  }}
                />

                <div className="mt-4 rounded-2xl border border-white/10 bg-slate-950/70 p-3">
                  <div className="flex items-center justify-between text-sm">
                    <span className="text-slate-400">รายการล่าสุด</span>
                    <button className="font-black text-sky-200" onClick={() => setActiveTab("records")} type="button">
                      ดูทั้งหมด
                    </button>
                  </div>
                  {latestRecord ? (
                    <div className="mt-3 rounded-xl bg-slate-900/70 p-3">
                      <p className="truncate text-sm font-black">{latestRecord.teamLeft} vs {latestRecord.teamRight}</p>
                      <p className="mt-1 text-xs text-slate-400">
                        ลง {getOutcomeLabel(latestRecord)} / {money(Number(latestRecord.stake || 0))}
                      </p>
                    </div>
                  ) : null}
                </div>
              </section>
            </aside>
          </div>
        </section>
      </div>
    </main>
  );
}

function SummaryStat({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="min-w-24 rounded-xl bg-slate-950/55 px-3 py-3">
      <p className="text-[11px] font-semibold text-slate-300/60">{label}</p>
      <p className={`mt-1 text-sm font-black sm:text-base ${highlight ? "text-sky-200" : "text-slate-50"}`}>
        {value}
      </p>
    </div>
  );
}

function SideNavItem({ active = false, icon, label }: { active?: boolean; icon: React.ReactNode; label: string }) {
  return (
    <button
      className={`flex w-full items-center gap-3 rounded-xl px-3 py-3 text-sm font-black transition ${
        active
          ? "bg-sky-400 text-slate-950 shadow-lg shadow-sky-500/20"
          : "text-slate-300 hover:bg-slate-900"
      }`}
      type="button"
    >
      {icon}
      {label}
    </button>
  );
}

function TabButton({
  active,
  icon,
  label,
  onClick,
}: {
  active: boolean;
  icon: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-black transition ${
        active ? "bg-sky-400 text-slate-950 shadow-lg shadow-sky-500/20" : "text-slate-300 hover:bg-slate-800/80"
      }`}
      onClick={onClick}
      type="button"
    >
      {icon}
      {label}
    </button>
  );
}

function TextField({
  disabled = false,
  label,
  onChange,
  placeholder,
  type = "text",
  value,
}: {
  disabled?: boolean;
  label: string;
  onChange: (value: string) => void;
  placeholder: string;
  type?: string;
  value: string;
}) {
  return (
    <label className="block">
      <span className="mb-2 block text-sm font-semibold text-slate-200/85">{label}</span>
      <input
        className="w-full rounded-xl border border-white/10 bg-slate-950/65 px-4 py-3 text-base font-semibold text-slate-50 outline-none transition placeholder:text-slate-500 focus:border-sky-400/80 disabled:opacity-30"
        disabled={disabled}
        inputMode={type === "number" ? "decimal" : "text"}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        type={type}
        value={value}
      />
    </label>
  );
}

function OutcomeButton({
  active,
  label,
  odds,
  onClick,
}: {
  active: boolean;
  label: string;
  odds: string;
  onClick: () => void;
}) {
  return (
    <button
      className={`rounded-xl border p-3 text-left transition ${
        active
          ? "border-sky-300 bg-sky-400 text-slate-950 shadow-lg shadow-blue-950/25"
          : "border-white/10 bg-slate-950/65 text-slate-50 hover:border-sky-400/35 hover:bg-sky-400/10"
      }`}
      onClick={onClick}
      type="button"
    >
      <p className="truncate text-xs font-black uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 text-xl font-black">{odds || "-"}</p>
    </button>
  );
}

function BetCard({
  onCopy,
  onDelete,
  onStatusChange,
  preview = false,
  record,
}: {
  onCopy: () => void;
  onDelete: () => void;
  onStatusChange: (status: BetStatus) => void;
  preview?: boolean;
  record: BetRecord;
}) {
  const selectedOdds = getSelectedOdds(record);
  const projectedProfit = getProjectedProfit(record);
  const status = statusConfig[record.status];

  return (
    <article className="rounded-2xl border border-white/10 bg-slate-950/75 p-3 shadow-xl shadow-black/25 backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-lg bg-sky-400/15 px-2.5 py-1 text-[11px] font-black text-sky-100">
              {record.sport}
            </span>
            <span className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-black ${status.className}`}>
              {status.icon}
              {status.label}
            </span>
          </div>
          <h3 className="mt-3 text-base font-black">
            {record.teamLeft} <span className="text-slate-300/35">vs</span> {record.teamRight}
          </h3>
          <p className="mt-1 text-xs font-semibold text-slate-500">{record.createdAt}</p>
        </div>

        {!preview ? (
          <div className="flex gap-2">
            <IconButton label="คัดลอก" onClick={onCopy}>
              <Copy className="h-4 w-4" />
            </IconButton>
            <IconButton label="ลบ" onClick={onDelete}>
              <Trash2 className="h-4 w-4" />
            </IconButton>
          </div>
        ) : null}
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl bg-slate-900/60 p-2">
        <MiniStat label="ลง" value={getOutcomeLabel(record)} />
        <MiniStat label="น้ำ" value={selectedOdds ? selectedOdds.toString() : "-"} />
        <MiniStat label="เงิน" value={money(Number(record.stake || 0))} />
      </div>

      <div className="mt-3 rounded-xl border border-sky-400/15 bg-sky-400/10 p-3">
        <p className="text-xs font-semibold text-slate-300/60">ถ้าชนะ ได้กำไรประมาณ</p>
        <p className="mt-1 text-xl font-black text-sky-200">+{money(projectedProfit)}</p>
      </div>

      {!preview ? (
        <div className="mt-3 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(Object.keys(statusConfig) as BetStatus[]).map((statusKey) => (
            <button
              className={`rounded-xl border px-3 py-2 text-xs font-black transition ${
                record.status === statusKey
                  ? statusConfig[statusKey].className
                  : "border-white/10 bg-slate-900/55 text-slate-200 hover:bg-sky-400/10"
              }`}
              key={statusKey}
              onClick={() => onStatusChange(statusKey)}
              type="button"
            >
              {statusConfig[statusKey].label}
            </button>
          ))}
        </div>
      ) : null}
    </article>
  );
}

function MiniStat({ label, value }: { label: string; value: string }) {
  return (
    <div className="min-w-0 rounded-lg bg-slate-950/55 p-2.5">
      <p className="text-[11px] font-semibold text-slate-300/55">{label}</p>
      <p className="mt-1 truncate text-sm font-black text-slate-50">{value}</p>
    </div>
  );
}

function IconButton({
  children,
  label,
  onClick,
}: {
  children: React.ReactNode;
  label: string;
  onClick: () => void;
}) {
  return (
    <button
      aria-label={label}
      className="rounded-xl border border-white/10 bg-slate-900/55 p-2.5 text-slate-200 transition hover:bg-sky-400/10"
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

function InfoTile({
  icon,
  label,
  positive = false,
  value,
}: {
  icon: React.ReactNode;
  label: string;
  positive?: boolean;
  value: string;
}) {
  return (
    <div className="flex items-center gap-3 rounded-xl border border-white/10 bg-slate-950/55 p-3">
      <div className="rounded-xl bg-sky-400/15 p-2.5 text-sky-100">{icon}</div>
      <div>
        <p className="text-xs font-semibold text-slate-300/60">{label}</p>
        <p className={`mt-1 text-xl font-black ${positive ? "text-sky-200" : "text-slate-50"}`}>{value}</p>
      </div>
    </div>
  );
}

function FilterButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      className={`rounded-xl border px-3 py-2.5 text-sm font-black transition ${
        active ? "border-sky-200 bg-sky-400 text-slate-950" : "border-white/10 bg-slate-900/55 text-slate-200"
      }`}
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  );
}
