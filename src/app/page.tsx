"use client";

import {
  ArrowLeftRight,
  Check,
  ClipboardList,
  Copy,
  Plus,
  RotateCcw,
  Trash2,
  Wallet,
  X,
} from "lucide-react";
import type { User } from "@supabase/supabase-js";
import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

type Outcome = "left" | "draw" | "right";
type BetStatus = "pending" | "won" | "lost" | "void";
type ActiveTab = "create" | "records";
type AuthMode = "login" | "signup";

type BetRecord = {
  id: string;
  userId: string;
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

type BetFormState = Omit<BetRecord, "id" | "userId" | "status" | "createdAt">;

type BetRecordRow = {
  id: string;
  user_id: string;
  team_left: string;
  team_right: string;
  has_draw: boolean;
  odds_left: number | null;
  odds_draw: number | null;
  odds_right: number | null;
  selected_outcome: Outcome;
  stake: number | null;
  status: BetStatus;
  created_at: string;
};

const SESSION_MAX_IDLE_MS = 7 * 24 * 60 * 60 * 1000;
const LAST_SEEN_KEY = "tradingclaw:last_seen";

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
    className: "border-blue-500/35 bg-blue-500/12 text-blue-100",
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
  teamLeft: "",
  teamRight: "",
  hasDraw: false,
  oddsLeft: "",
  oddsDraw: "",
  oddsRight: "",
  selectedOutcome: "left",
  stake: "",
};

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

function formatDate(value: string) {
  return new Intl.DateTimeFormat("th-TH", {
    day: "2-digit",
    month: "short",
    hour: "2-digit",
    minute: "2-digit",
  }).format(new Date(value));
}

function rowToRecord(row: BetRecordRow): BetRecord {
  return {
    id: row.id,
    userId: row.user_id,
    teamLeft: row.team_left,
    teamRight: row.team_right,
    hasDraw: row.has_draw,
    oddsLeft: row.odds_left?.toString() ?? "",
    oddsDraw: row.odds_draw?.toString() ?? "",
    oddsRight: row.odds_right?.toString() ?? "",
    selectedOutcome: row.selected_outcome,
    stake: row.stake?.toString() ?? "",
    status: row.status,
    createdAt: formatDate(row.created_at),
  };
}

function identifierToEmail(identifier: string) {
  const value = identifier.trim().toLowerCase();

  if (value.includes("@")) {
    return value;
  }

  const normalized = value.replace(/[^a-z0-9._-]/g, "_");
  return `${normalized}@tradingclaw.app`;
}

function passwordForAuth(password: string) {
  return password.length >= 6 ? password : `tc-${password}-pass`;
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("create");
  const [records, setRecords] = useState<BetRecord[]>([]);
  const [form, setForm] = useState<BetFormState>(initialForm);
  const [user, setUser] = useState<User | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authMessage, setAuthMessage] = useState("");
  const [isAuthLoading, setIsAuthLoading] = useState(true);
  const [isSaving, setIsSaving] = useState(false);

  const canSave =
    form.teamLeft.trim() &&
    form.teamRight.trim() &&
    form.stake.trim() &&
    (form.selectedOutcome !== "draw" || form.hasDraw);

  const loadRecords = useCallback(async (userId: string) => {
    const { data, error } = await supabase
      .from("bet_records")
      .select("*")
      .eq("user_id", userId)
      .order("created_at", { ascending: false });

    if (error) {
      setAuthMessage(error.message);
      return;
    }

    setRecords((data as BetRecordRow[]).map(rowToRecord));
  }, []);

  useEffect(() => {
    let isMounted = true;

    async function initAuth() {
      const lastSeen = Number(localStorage.getItem(LAST_SEEN_KEY) || 0);

      if (lastSeen && Date.now() - lastSeen > SESSION_MAX_IDLE_MS) {
        await supabase.auth.signOut();
        localStorage.removeItem(LAST_SEEN_KEY);
      }

      const { data } = await supabase.auth.getSession();

      if (!isMounted) return;

      setUser(data.session?.user ?? null);
      setIsAuthLoading(false);

      if (data.session?.user) {
        localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
        await loadRecords(data.session.user.id);
      }
    }

    initAuth();

    const { data: listener } = supabase.auth.onAuthStateChange((_event, session) => {
      setUser(session?.user ?? null);
      if (session?.user) {
        localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
        void loadRecords(session.user.id);
      } else {
        setRecords([]);
      }
    });

    return () => {
      isMounted = false;
      listener.subscription.unsubscribe();
    };
  }, [loadRecords]);

  function updateForm(key: keyof BetFormState, value: string | boolean) {
    setForm((current) => {
      if (key === "hasDraw" && value === false && current.selectedOutcome === "draw") {
        return { ...current, hasDraw: false, oddsDraw: "", selectedOutcome: "left" };
      }

      return { ...current, [key]: value };
    });
  }

  async function handleLogin() {
    if (!username.trim() || !password) {
      setAuthMessage("กรอกชื่อผู้ใช้และรหัสผ่านก่อน");
      return;
    }

    const email = identifierToEmail(username);
    const authPassword = passwordForAuth(password);

    setIsAuthLoading(true);
    setAuthMessage("");

    const signIn = await supabase.auth.signInWithPassword({
      email,
      password: authPassword,
    });

    if (signIn.error) {
      setAuthMessage("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง ถ้ายังไม่มีบัญชีให้กดสมัคร");
      setIsAuthLoading(false);
      return;
    }

    localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
    setIsAuthLoading(false);
  }

  async function handleSignUp() {
    if (!username.trim() || !password) {
      setAuthMessage("กรอกชื่อผู้ใช้และรหัสผ่านก่อนสมัคร");
      return;
    }

    const email = identifierToEmail(username);
    const authPassword = passwordForAuth(password);

    setIsAuthLoading(true);
    setAuthMessage("");

    const signUp = await supabase.auth.signUp({
      email,
      password: authPassword,
      options: {
        data: {
          username: username.trim(),
        },
      },
    });

    if (signUp.error) {
      setAuthMessage(signUp.error.message);
      setIsAuthLoading(false);
      return;
    }

    if (!signUp.data.session) {
      setAuthMessage("สมัครแล้ว แต่ Supabase เปิด email confirmation อยู่ ต้องปิด confirmation ก่อนถึงจะล็อกอินทันทีได้");
      setIsAuthLoading(false);
      return;
    }

    localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
    setIsAuthLoading(false);
  }

  async function handleLogout() {
    await supabase.auth.signOut();
    localStorage.removeItem(LAST_SEEN_KEY);
    setUser(null);
    setRecords([]);
  }

  async function saveRecord() {
    if (!canSave || !user || isSaving) return;

    setIsSaving(true);

    const { error } = await supabase.from("bet_records").insert({
      user_id: user.id,
      team_left: form.teamLeft.trim(),
      team_right: form.teamRight.trim(),
      has_draw: form.hasDraw,
      odds_left: form.oddsLeft ? Number(form.oddsLeft) : null,
      odds_draw: form.hasDraw && form.oddsDraw ? Number(form.oddsDraw) : null,
      odds_right: form.oddsRight ? Number(form.oddsRight) : null,
      selected_outcome: form.selectedOutcome,
      stake: Number(form.stake || 0),
      status: "pending",
    });

    setIsSaving(false);

    if (error) {
      setAuthMessage(error.message);
      return;
    }

    setForm({
      ...initialForm,
      hasDraw: form.hasDraw,
    });
    setActiveTab("records");
    await loadRecords(user.id);
  }

  async function setRecordStatus(id: string, status: BetStatus) {
    const { error } = await supabase.from("bet_records").update({ status }).eq("id", id);

    if (error) {
      setAuthMessage(error.message);
      return;
    }

    setRecords((current) => current.map((record) => (record.id === id ? { ...record, status } : record)));
  }

  function copyRecord(record: BetRecord) {
    setForm({
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

  async function deleteRecord(id: string) {
    const { error } = await supabase.from("bet_records").delete().eq("id", id);

    if (error) {
      setAuthMessage(error.message);
      return;
    }

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

  if (isAuthLoading && !user) {
    return (
      <main className="grid min-h-screen place-items-center px-4 py-5 text-slate-50">
        <div className="w-full max-w-[420px] rounded-[28px] border border-slate-700/50 bg-[#0a1020] p-5 text-center shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
          <p className="text-sm font-bold text-slate-400">กำลังตรวจสอบ session...</p>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="grid min-h-screen place-items-center px-4 py-5 text-slate-50">
        <section className="w-full max-w-[420px] rounded-[28px] border border-slate-700/50 bg-[#0a1020] p-5 shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
          <div className="mb-5">
            <p className="text-[11px] font-extrabold uppercase tracking-[0.22em] text-blue-300/55">Account</p>
            <h1 className="mt-1 text-2xl font-extrabold tracking-tight">
              {authMode === "login" ? "เข้าสู่ระบบ" : "สมัครบัญชี"}
            </h1>
            <p className="mt-2 text-sm text-slate-400">
              {authMode === "login" ? "ใช้ชื่อผู้ใช้หรืออีเมลที่สมัครไว้" : "ใช้อะไรก็ได้เป็นชื่อผู้ใช้ หรือใส่อีเมลจริงก็ได้"}
            </p>
          </div>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-2 rounded-2xl bg-[#0d1526] p-2">
              <button
                className={`rounded-xl px-4 py-3 text-sm font-extrabold transition ${
                  authMode === "login" ? "bg-blue-500 text-white" : "text-slate-400 hover:bg-[#111a2b]"
                }`}
                onClick={() => {
                  setAuthMode("login");
                  setAuthMessage("");
                }}
                type="button"
              >
                เข้าสู่ระบบ
              </button>
              <button
                className={`rounded-xl px-4 py-3 text-sm font-extrabold transition ${
                  authMode === "signup" ? "bg-blue-500 text-white" : "text-slate-400 hover:bg-[#111a2b]"
                }`}
                onClick={() => {
                  setAuthMode("signup");
                  setAuthMessage("");
                }}
                type="button"
              >
                สมัคร
              </button>
            </div>
            <TextField label="ชื่อผู้ใช้ / อีเมล" onChange={setUsername} placeholder="เช่น best หรือ best@mail.com" value={username} />
            <TextField label="รหัสผ่าน" onChange={setPassword} placeholder="ต้องใส่รหัสผ่าน" type="password" value={password} />
            {authMessage ? <p className="rounded-xl border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{authMessage}</p> : null}
            <button
              className="w-full rounded-2xl bg-blue-500 px-5 py-4 text-base font-extrabold text-white transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-40"
              disabled={isAuthLoading || !username.trim() || !password}
              onClick={authMode === "login" ? handleLogin : handleSignUp}
              type="button"
            >
              {isAuthLoading ? "กำลังทำรายการ..." : authMode === "login" ? "เข้าใช้งาน" : "สมัครบัญชี"}
            </button>
          </div>
        </section>
      </main>
    );
  }

  return (
    <main className="min-h-screen px-4 py-5 text-slate-50">
      <div className="mx-auto flex min-h-screen w-full max-w-[760px]">
        <section className="flex w-full min-w-0 flex-col">
          <div className="block">
            <div className="min-w-0">
              <section className="overflow-hidden rounded-[28px] border border-slate-700/50 bg-[#0a1020] shadow-[0_18px_48px_rgba(0,0,0,0.32)]">
                <div className="grid grid-cols-2 gap-2 border-b border-slate-800 bg-[#0d1526] p-2">
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
                  <div className="p-4">
                    <div className="mb-4 flex items-center justify-between gap-3">
                      <div>
                        <p className="text-[11px] font-extrabold uppercase tracking-[0.22em] text-blue-300/55">Market Builder</p>
                        <h2 className="mt-1 text-xl font-extrabold tracking-tight">สร้างคู่แข่งขัน</h2>
                      </div>
                      <div className="flex gap-2">
                        <button
                          className="inline-flex items-center gap-2 rounded-xl border border-slate-700/70 bg-[#111a2b] px-3 py-2 text-sm font-bold text-slate-200 transition hover:border-blue-500/40 hover:bg-[#132033]"
                          onClick={swapTeams}
                          type="button"
                        >
                          <ArrowLeftRight className="h-4 w-4" />
                          สลับทีม
                        </button>
                        <button
                          className="rounded-xl border border-slate-700/70 bg-[#111a2b] px-3 py-2 text-sm font-bold text-slate-400 transition hover:text-slate-100"
                          onClick={handleLogout}
                          type="button"
                        >
                          ออก
                        </button>
                      </div>
                    </div>
                    {authMessage ? <p className="mb-4 rounded-xl border border-rose-400/30 bg-rose-400/10 p-3 text-sm text-rose-100">{authMessage}</p> : null}

                    <div className="rounded-2xl border border-slate-800 bg-[#0d1627] p-3 shadow-inner shadow-black/10">
                      <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-3">
                        <TextField
                          label="ทีมซ้าย"
                          onChange={(value) => updateForm("teamLeft", value)}
                          placeholder="เช่น Arsenal"
                          value={form.teamLeft}
                        />
                        <div className="pb-4 text-center text-xs font-black text-slate-500">VS</div>
                        <TextField
                          label="ทีมขวา"
                          onChange={(value) => updateForm("teamRight", value)}
                          placeholder="เช่น Chelsea"
                          value={form.teamRight}
                        />
                      </div>

                      <div className="mt-4 grid grid-cols-3 gap-3">
                        <TextField
                          label={`น้ำ ${form.teamLeft || "ทีมซ้าย"}`}
                          onChange={(value) => updateForm("oddsLeft", value)}
                          placeholder="1.85"
                          type="number"
                          value={form.oddsLeft}
                        />
                        <div className={form.hasDraw ? "block" : "opacity-35"}>
                          <TextField
                            disabled={!form.hasDraw}
                            label="น้ำเสมอ"
                            onChange={(value) => updateForm("oddsDraw", value)}
                            placeholder="3.50"
                            type="number"
                            value={form.oddsDraw}
                          />
                        </div>
                        <TextField
                          label={`น้ำ ${form.teamRight || "ทีมขวา"}`}
                          onChange={(value) => updateForm("oddsRight", value)}
                          placeholder="1.95"
                          type="number"
                          value={form.oddsRight}
                        />
                      </div>
                    </div>

                    <div className="mt-4 flex items-center justify-between gap-3 rounded-2xl border border-slate-800 bg-[#0d1627] p-3 shadow-inner shadow-black/10">
                      <div>
                        <p className="font-extrabold">ตลาด 1X2</p>
                        <p className="text-xs text-slate-400">เปิดเสมอเมื่อรายการนี้มีราคา X</p>
                      </div>
                      <button
                        className={`rounded-xl px-4 py-2 text-sm font-black transition ${
                          form.hasDraw ? "bg-blue-500 text-slate-50" : "bg-[#111a2b] text-slate-300"
                        }`}
                        onClick={() => updateForm("hasDraw", !form.hasDraw)}
                        type="button"
                      >
                        {form.hasDraw ? "มีเสมอ" : "ไม่มีเสมอ"}
                      </button>
                    </div>

                    <div className="mt-4 rounded-2xl border border-slate-800 bg-[#0d1627] p-3 shadow-inner shadow-black/10">
                      <div className="mb-3 flex items-center justify-between">
                        <p className="text-sm font-extrabold text-slate-200">Pick</p>
                        <p className="text-xs font-bold text-slate-500">เลือก odds ที่ลง</p>
                      </div>
                      <div className={`grid gap-2 ${form.hasDraw ? "grid-cols-3" : "grid-cols-2"}`}>
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

                    <div className="mt-4">
                      <TextField
                        label="จำนวนเงิน"
                        onChange={(value) => updateForm("stake", value)}
                        placeholder="1000"
                        type="number"
                        value={form.stake}
                      />
                    </div>

                    <button
                      className="mt-4 w-full rounded-2xl bg-blue-500 px-5 py-4 text-base font-extrabold text-white transition hover:bg-blue-400 disabled:cursor-not-allowed disabled:opacity-40"
                      disabled={!canSave || isSaving}
                      onClick={saveRecord}
                      type="button"
                    >
                      {isSaving ? "กำลังบันทึก..." : "Add to Bet Slip"}
                    </button>
                  </div>
                ) : (
                  <div className="space-y-3 p-4">
                    {records.length ? (
                      records.map((record) => (
                        <BetCard
                          key={record.id}
                          onCopy={() => copyRecord(record)}
                          onDelete={() => deleteRecord(record.id)}
                          onStatusChange={(status) => setRecordStatus(record.id, status)}
                          record={record}
                        />
                      ))
                    ) : (
                      <div className="rounded-2xl border border-dashed border-blue-500/15 bg-blue-500/[0.04] p-8 text-center text-slate-300/75">
                        ยังไม่มีรายการ
                      </div>
                    )}
                  </div>
                )}
              </section>
            </div>

          </div>
        </section>
      </div>
    </main>
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
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-extrabold transition ${
        active ? "bg-blue-500 text-white" : "text-slate-400 hover:bg-[#111a2b] hover:text-slate-100"
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
      <span className="mb-2 block text-[13px] font-bold text-slate-300">{label}</span>
      <input
        className="w-full rounded-xl border border-slate-700/70 bg-[#08101d] px-4 py-3 text-base font-semibold text-slate-50 outline-none transition placeholder:text-slate-600 focus:border-blue-500/70 focus:bg-[#0a1424] disabled:opacity-30"
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
          ? "border-blue-500 bg-blue-500 text-white"
          : "border-slate-700/70 bg-[#08101d] text-slate-50 hover:border-blue-500/40 hover:bg-[#0d1a2c]"
      }`}
      onClick={onClick}
      type="button"
    >
      <p className="truncate text-xs font-extrabold uppercase tracking-wide opacity-70">{label}</p>
      <p className="mt-1 text-xl font-extrabold">{odds || "-"}</p>
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
  const status = statusConfig[record.status];

  return (
    <article className="rounded-2xl border border-slate-800 bg-[#0d1627] p-3 shadow-lg shadow-black/20">
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div>
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded-lg border px-2.5 py-1 text-[11px] font-extrabold ${status.className}`}>
              {status.icon}
              {status.label}
            </span>
          </div>
          <h3 className="mt-3 text-base font-extrabold">
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

      <div className="mt-3 grid grid-cols-2 gap-2 rounded-xl bg-[#08101d] p-2">
        <MiniStat label="ลง" value={getOutcomeLabel(record)} />
        <MiniStat label="น้ำ" value={selectedOdds ? selectedOdds.toString() : "-"} />
      </div>

      {!preview ? (
        <div className="mt-3 grid grid-cols-4 gap-2">
          {(Object.keys(statusConfig) as BetStatus[]).map((statusKey) => (
            <button
              className={`rounded-xl border px-3 py-2 text-xs font-extrabold transition ${
                record.status === statusKey
                  ? statusConfig[statusKey].className
                  : "border-slate-700/70 bg-[#08101d] text-slate-300 hover:bg-blue-500/10"
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
    <div className="min-w-0 rounded-lg bg-[#0b1423] p-2.5">
      <p className="text-[11px] font-semibold text-slate-300/55">{label}</p>
      <p className="mt-1 truncate text-sm font-extrabold text-slate-50">{value}</p>
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
      className="rounded-xl border border-slate-700/70 bg-[#08101d] p-2.5 text-slate-300 transition hover:bg-blue-500/10"
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

