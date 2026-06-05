"use client";

import {
  ArrowLeftRight,
  Check,
  ClipboardList,
  Copy,
  Flame,
  Plus,
  RotateCcw,
  Trash2,
  Trophy,
  Wallet,
  X,
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
    className: "border-amber-400/40 bg-amber-400/15 text-amber-100",
    icon: <RotateCcw className="h-4 w-4" />,
  },
  won: {
    label: "ชนะ",
    className: "border-emerald-400/40 bg-emerald-400/15 text-emerald-100",
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

  return (
    <main className="min-h-screen px-4 py-5 text-emerald-50 sm:px-6 lg:px-8">
      <div className="mx-auto flex w-full max-w-6xl flex-col gap-5">
        <header className="overflow-hidden rounded-[2rem] border border-white/10 bg-white/[0.06] p-5 shadow-2xl shadow-black/25 backdrop-blur">
          <div className="flex flex-col gap-4 sm:flex-row sm:items-center sm:justify-between">
            <div>
              <div className="mb-2 inline-flex items-center gap-2 rounded-full border border-emerald-300/20 bg-emerald-300/10 px-3 py-1 text-xs font-semibold text-emerald-100">
                <Flame className="h-3.5 w-3.5" />
                จดไว ไม่ต้องคิดเยอะ
              </div>
              <h1 className="text-3xl font-black tracking-tight sm:text-4xl">TradingClaw</h1>
              <p className="mt-2 max-w-2xl text-sm text-emerald-100/70">
                UI สำหรับจดรายการลงพนันแบบเร็ว เลือกฝั่งเหมือนเว็บพนัน แล้วค่อยมาตัดผลชนะ/แพ้ในเมนูรายการ
              </p>
            </div>

            <div className="grid grid-cols-3 gap-2 rounded-3xl border border-white/10 bg-black/20 p-2 text-center">
              <SummaryStat label="ลงทั้งหมด" value={money(summary.totalStake)} />
              <SummaryStat label="ค้างผล" value={money(summary.pending)} />
              <SummaryStat
                label="กำไรสุทธิ"
                value={`${summary.net >= 0 ? "+" : ""}${money(summary.net)}`}
                highlight={summary.net >= 0}
              />
            </div>
          </div>
        </header>

        <nav className="sticky top-3 z-20 grid grid-cols-2 gap-2 rounded-3xl border border-white/10 bg-[#07110d]/85 p-2 shadow-xl shadow-black/20 backdrop-blur">
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
        </nav>

        {activeTab === "create" ? (
          <section className="grid gap-5 lg:grid-cols-[1.1fr_0.9fr]">
            <div className="rounded-[2rem] border border-white/10 bg-white/[0.07] p-4 shadow-2xl shadow-black/20 backdrop-blur sm:p-6">
              <div className="mb-5 flex items-center justify-between gap-3">
                <div>
                  <h2 className="text-xl font-bold">สร้างรายการ</h2>
                  <p className="text-sm text-emerald-100/60">กรอกคู่แข่ง เลือกฝั่ง ใส่เงิน แล้วบันทึก</p>
                </div>
                <button
                  className="inline-flex items-center gap-2 rounded-full border border-white/10 bg-white/10 px-3 py-2 text-sm font-semibold text-emerald-50 transition hover:bg-white/15"
                  onClick={swapTeams}
                  type="button"
                >
                  <ArrowLeftRight className="h-4 w-4" />
                  สลับทีม
                </button>
              </div>

              <div className="space-y-5">
                <div>
                  <label className="mb-2 block text-sm font-semibold text-emerald-100/80">กีฬา</label>
                  <div className="grid grid-cols-3 gap-2 sm:grid-cols-5">
                    {sports.map((sport) => (
                      <button
                        className={`rounded-2xl border px-3 py-3 text-sm font-bold transition ${
                          form.sport === sport
                            ? "border-emerald-300 bg-emerald-300 text-emerald-950"
                            : "border-white/10 bg-black/20 text-emerald-100 hover:bg-white/10"
                        }`}
                        key={sport}
                        onClick={() => updateForm("sport", sport)}
                        type="button"
                      >
                        {sport}
                      </button>
                    ))}
                  </div>
                </div>

                <div className="grid gap-3 sm:grid-cols-[1fr_auto_1fr] sm:items-end">
                  <TextField
                    label="ทีมซ้าย"
                    onChange={(value) => updateForm("teamLeft", value)}
                    placeholder="เช่น Arsenal"
                    value={form.teamLeft}
                  />
                  <div className="hidden pb-4 text-center text-sm font-black text-emerald-100/40 sm:block">VS</div>
                  <TextField
                    label="ทีมขวา"
                    onChange={(value) => updateForm("teamRight", value)}
                    placeholder="เช่น Chelsea"
                    value={form.teamRight}
                  />
                </div>

                <div className="grid gap-3 sm:grid-cols-3">
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

                <div className="flex flex-wrap items-center justify-between gap-3 rounded-3xl border border-white/10 bg-black/20 p-3">
                  <div>
                    <p className="font-bold">มีเสมอไหม?</p>
                    <p className="text-xs text-emerald-100/60">ถ้าไม่เปิด จะเหลือแค่เลือกซ้าย/ขวา</p>
                  </div>
                  <button
                    className={`rounded-full px-4 py-2 text-sm font-black transition ${
                      form.hasDraw ? "bg-emerald-300 text-emerald-950" : "bg-white/10 text-emerald-50"
                    }`}
                    onClick={() => updateForm("hasDraw", !form.hasDraw)}
                    type="button"
                  >
                    {form.hasDraw ? "เปิดเสมอ" : "ไม่มีเสมอ"}
                  </button>
                </div>

                <div>
                  <label className="mb-2 block text-sm font-semibold text-emerald-100/80">เลือกที่ลง</label>
                  <div className={`grid gap-3 ${form.hasDraw ? "sm:grid-cols-3" : "sm:grid-cols-2"}`}>
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

                <div className="grid gap-3 sm:grid-cols-[1fr_auto]">
                  <TextField
                    label="จำนวนเงิน"
                    onChange={(value) => updateForm("stake", value)}
                    placeholder="1000"
                    type="number"
                    value={form.stake}
                  />
                  <button
                    className="self-end rounded-2xl border border-white/10 bg-white/10 px-4 py-3 text-sm font-bold text-emerald-50 transition hover:bg-white/15"
                    onClick={() => updateForm("stake", lastStake)}
                    type="button"
                  >
                    ลงเท่าเดิม {money(Number(lastStake || 0))}
                  </button>
                </div>

                <button
                  className="w-full rounded-3xl bg-gradient-to-r from-emerald-300 to-lime-300 px-5 py-4 text-lg font-black text-emerald-950 shadow-xl shadow-emerald-950/30 transition hover:scale-[1.01] disabled:cursor-not-allowed disabled:opacity-40 disabled:hover:scale-100"
                  disabled={!canSave}
                  onClick={saveRecord}
                  type="button"
                >
                  บันทึกรายการ
                </button>
              </div>
            </div>

            <aside className="rounded-[2rem] border border-white/10 bg-black/20 p-4 shadow-2xl shadow-black/20 sm:p-6">
              <h2 className="mb-4 text-xl font-bold">ตัวอย่างบิลที่จะได้</h2>
              <BetCard
                onCopy={() => undefined}
                onDelete={() => undefined}
                onStatusChange={() => undefined}
                record={{
                  ...form,
                  id: "preview",
                  status: "pending",
                  createdAt: "ตอนนี้",
                  teamLeft: form.teamLeft || "ทีมซ้าย",
                  teamRight: form.teamRight || "ทีมขวา",
                  stake: form.stake || "0",
                }}
                preview
              />
              <div className="mt-4 rounded-3xl border border-emerald-300/20 bg-emerald-300/10 p-4 text-sm text-emerald-100/75">
                <p className="font-bold text-emerald-50">แนวคิด UI</p>
                <p className="mt-1">
                  หน้าแรกเน้นกรอกให้เสร็จในจอเดียว ส่วนการตัดผลกับดูสรุปย้ายไปเมนูรายการเพื่อไม่ให้ฟอร์มรก
                </p>
              </div>
            </aside>
          </section>
        ) : (
          <section className="grid gap-5 lg:grid-cols-[0.8fr_1.2fr]">
            <aside className="rounded-[2rem] border border-white/10 bg-white/[0.07] p-4 shadow-2xl shadow-black/20 sm:p-6">
              <h2 className="text-xl font-bold">สรุปรายการ</h2>
              <p className="mt-1 text-sm text-emerald-100/60">เอาไว้ดูภาพรวมก่อนตัดผล</p>

              <div className="mt-5 grid gap-3">
                <InfoTile icon={<Wallet className="h-5 w-5" />} label="เงินที่ลงทั้งหมด" value={money(summary.totalStake)} />
                <InfoTile icon={<RotateCcw className="h-5 w-5" />} label="รอผล" value={money(summary.pending)} />
                <InfoTile
                  icon={<Trophy className="h-5 w-5" />}
                  label="กำไรสุทธิ"
                  positive={summary.net >= 0}
                  value={`${summary.net >= 0 ? "+" : ""}${money(summary.net)}`}
                />
              </div>

              <div className="mt-5">
                <p className="mb-2 text-sm font-semibold text-emerald-100/80">กรองสถานะ</p>
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
                <div className="rounded-[2rem] border border-dashed border-white/15 bg-white/[0.04] p-8 text-center text-emerald-100/70">
                  ยังไม่มีรายการในตัวกรองนี้
                </div>
              )}
            </div>
          </section>
        )}
      </div>
    </main>
  );
}

function SummaryStat({ label, value, highlight = false }: { label: string; value: string; highlight?: boolean }) {
  return (
    <div className="min-w-24 rounded-2xl bg-white/5 px-3 py-3">
      <p className="text-[11px] font-semibold text-emerald-100/55">{label}</p>
      <p className={`mt-1 text-sm font-black sm:text-base ${highlight ? "text-lime-200" : "text-emerald-50"}`}>
        {value}
      </p>
    </div>
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
      className={`inline-flex items-center justify-center gap-2 rounded-2xl px-4 py-3 text-sm font-black transition ${
        active ? "bg-emerald-300 text-emerald-950" : "text-emerald-100 hover:bg-white/10"
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
      <span className="mb-2 block text-sm font-semibold text-emerald-100/80">{label}</span>
      <input
        className="w-full rounded-2xl border border-white/10 bg-black/25 px-4 py-3 text-base font-semibold text-emerald-50 outline-none transition placeholder:text-emerald-100/30 focus:border-emerald-300/70 disabled:opacity-30"
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
      className={`rounded-3xl border p-4 text-left transition ${
        active
          ? "border-emerald-200 bg-emerald-300 text-emerald-950 shadow-lg shadow-emerald-950/20"
          : "border-white/10 bg-black/25 text-emerald-50 hover:bg-white/10"
      }`}
      onClick={onClick}
      type="button"
    >
      <p className="truncate text-sm font-bold opacity-80">{label}</p>
      <p className="mt-1 text-2xl font-black">{odds || "-"}</p>
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
    <article className="rounded-[1.7rem] border border-white/10 bg-white/[0.07] p-4 shadow-xl shadow-black/15 backdrop-blur">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className="rounded-full bg-emerald-300/15 px-3 py-1 text-xs font-black text-emerald-100">
              {record.sport}
            </span>
            <span className={`inline-flex items-center gap-1 rounded-full border px-3 py-1 text-xs font-black ${status.className}`}>
              {status.icon}
              {status.label}
            </span>
          </div>
          <h3 className="mt-3 text-lg font-black">
            {record.teamLeft} <span className="text-emerald-100/35">vs</span> {record.teamRight}
          </h3>
          <p className="mt-1 text-sm text-emerald-100/55">{record.createdAt}</p>
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

      <div className="mt-4 grid grid-cols-3 gap-2 rounded-3xl bg-black/20 p-2">
        <MiniStat label="ลง" value={getOutcomeLabel(record)} />
        <MiniStat label="น้ำ" value={selectedOdds ? selectedOdds.toString() : "-"} />
        <MiniStat label="เงิน" value={money(Number(record.stake || 0))} />
      </div>

      <div className="mt-3 rounded-3xl border border-emerald-300/15 bg-emerald-300/10 p-3">
        <p className="text-xs font-semibold text-emerald-100/55">ถ้าชนะ ได้กำไรประมาณ</p>
        <p className="mt-1 text-2xl font-black text-lime-200">+{money(projectedProfit)}</p>
      </div>

      {!preview ? (
        <div className="mt-4 grid grid-cols-2 gap-2 sm:grid-cols-4">
          {(Object.keys(statusConfig) as BetStatus[]).map((statusKey) => (
            <button
              className={`rounded-2xl border px-3 py-2 text-sm font-black transition ${
                record.status === statusKey
                  ? statusConfig[statusKey].className
                  : "border-white/10 bg-black/20 text-emerald-100 hover:bg-white/10"
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
    <div className="min-w-0 rounded-2xl bg-white/5 p-3">
      <p className="text-[11px] font-semibold text-emerald-100/50">{label}</p>
      <p className="mt-1 truncate text-sm font-black text-emerald-50">{value}</p>
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
      className="rounded-2xl border border-white/10 bg-black/20 p-3 text-emerald-100 transition hover:bg-white/10"
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
    <div className="flex items-center gap-3 rounded-3xl border border-white/10 bg-black/20 p-4">
      <div className="rounded-2xl bg-emerald-300/15 p-3 text-emerald-100">{icon}</div>
      <div>
        <p className="text-xs font-semibold text-emerald-100/55">{label}</p>
        <p className={`mt-1 text-xl font-black ${positive ? "text-lime-200" : "text-emerald-50"}`}>{value}</p>
      </div>
    </div>
  );
}

function FilterButton({ active, label, onClick }: { active: boolean; label: string; onClick: () => void }) {
  return (
    <button
      className={`rounded-2xl border px-3 py-3 text-sm font-black transition ${
        active ? "border-emerald-200 bg-emerald-300 text-emerald-950" : "border-white/10 bg-black/20 text-emerald-100"
      }`}
      onClick={onClick}
      type="button"
    >
      {label}
    </button>
  );
}
