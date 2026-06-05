"use client";

import {
  BarChart3,
  Check,
  ClipboardList,
  Copy,
  Plus,
  RotateCcw,
  Search,
  Trash2,
  UserRound,
  Wallet,
  X,
} from "lucide-react";
import { useCallback, useEffect, useState } from "react";
import { supabase } from "@/lib/supabase";

type Outcome = "left" | "draw" | "right";
type BetStatus = "pending" | "won" | "lost" | "void";
type ActiveTab = "create" | "records" | "profile";
type AuthMode = "login" | "signup";

type AppUser = {
  id: string;
  identifier: string;
};

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

type UserSearchResult = {
  identifier: string;
  record_count: number;
};

type ProfileStats = {
  grossReturn: number;
  lostCount: number;
  netProfit: number;
  pendingCount: number;
  settledCount: number;
  totalRecords: number;
  totalStake: number;
  unitGrossReturn: number;
  unitNetProfit: number;
  unitRoi: number;
  voidCount: number;
  winCount: number;
  winRate: number;
};

const SESSION_MAX_IDLE_MS = 7 * 24 * 60 * 60 * 1000;
const LAST_SEEN_KEY = "tradingclaw:last_seen";
const SESSION_TOKEN_KEY = "tradingclaw:session_token";

const statusConfig: Record<
  BetStatus,
  { label: string; className: string; icon: React.ReactNode }
> = {
  pending: {
    label: "รอผล",
    className: "border-[#2a3542] bg-[#1b2531] text-[#b7c4d6]",
    icon: <RotateCcw className="h-4 w-4" />,
  },
  won: {
    label: "ชนะ",
    className: "border-[#2a3542] bg-[#1b2531] text-[#b7c4d6]",
    icon: <Check className="h-4 w-4" />,
  },
  lost: {
    label: "แพ้",
    className: "border-[#2a3542] bg-[#1b2531] text-[#b7c4d6]",
    icon: <X className="h-4 w-4" />,
  },
  void: {
    label: "คืนทุน",
    className: "border-[#2a3542] bg-[#1b2531] text-[#d5deec]",
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

function isDecimalInput(value: string) {
  return /^\d*(?:[.,]\d*)?$/.test(value);
}

function parseDecimal(value: string) {
  const normalizedValue = value.trim().replace(",", ".");

  if (!normalizedValue || normalizedValue === ".") {
    return null;
  }

  const parsedValue = Number(normalizedValue);
  return Number.isFinite(parsedValue) ? parsedValue : null;
}

function formatAmount(value: string) {
  const amount = parseDecimal(value);

  if (amount === null) {
    return "-";
  }

  return amount.toLocaleString("th-TH");
}

function formatNumber(value: number, maximumFractionDigits = 2) {
  return value.toLocaleString("th-TH", {
    maximumFractionDigits,
  });
}

function formatSignedAmount(value: number) {
  const sign = value > 0 ? "+" : "";
  return `${sign}${formatNumber(value)}`;
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

function getSelectedOdds(record: BetRecord) {
  if (record.selectedOutcome === "draw") {
    return parseDecimal(record.oddsDraw);
  }

  if (record.selectedOutcome === "right") {
    return parseDecimal(record.oddsRight);
  }

  return parseDecimal(record.oddsLeft);
}

function calculateProfileStats(records: BetRecord[]): ProfileStats {
  const settledRecords = records.filter((record) => record.status === "won" || record.status === "lost");
  const winCount = settledRecords.filter((record) => record.status === "won").length;
  const lostCount = settledRecords.filter((record) => record.status === "lost").length;

  const summary = settledRecords.reduce(
    (summary, record) => {
      const stake = parseDecimal(record.stake) ?? 0;
      const odds = getSelectedOdds(record) ?? 0;

      if (record.status === "won") {
        const grossReturn = odds > 0 ? stake * odds : 0;
        return {
          grossReturn: summary.grossReturn + grossReturn,
          netProfit: summary.netProfit + (odds > 0 ? grossReturn - stake : 0),
          totalStake: summary.totalStake + stake,
          unitGrossReturn: summary.unitGrossReturn + (odds > 0 ? odds : 0),
          unitNetProfit: summary.unitNetProfit + (odds > 0 ? odds - 1 : 0),
        };
      }

      return {
        grossReturn: summary.grossReturn,
        netProfit: summary.netProfit - stake,
        totalStake: summary.totalStake + stake,
        unitGrossReturn: summary.unitGrossReturn,
        unitNetProfit: summary.unitNetProfit - 1,
      };
    },
    { grossReturn: 0, netProfit: 0, totalStake: 0, unitGrossReturn: 0, unitNetProfit: 0 },
  );

  return {
    grossReturn: summary.grossReturn,
    lostCount,
    netProfit: summary.netProfit,
    pendingCount: records.filter((record) => record.status === "pending").length,
    settledCount: settledRecords.length,
    totalRecords: records.length,
    totalStake: summary.totalStake,
    unitGrossReturn: summary.unitGrossReturn,
    unitNetProfit: summary.unitNetProfit,
    unitRoi: settledRecords.length ? (summary.unitNetProfit / settledRecords.length) * 100 : 0,
    voidCount: records.filter((record) => record.status === "void").length,
    winCount,
    winRate: settledRecords.length ? (winCount / settledRecords.length) * 100 : 0,
  };
}

export default function Home() {
  const [activeTab, setActiveTab] = useState<ActiveTab>("create");
  const [records, setRecords] = useState<BetRecord[]>([]);
  const [form, setForm] = useState<BetFormState>(initialForm);
  const [user, setUser] = useState<AppUser | null>(null);
  const [username, setUsername] = useState("");
  const [password, setPassword] = useState("");
  const [authMode, setAuthMode] = useState<AuthMode>("login");
  const [authMessage, setAuthMessage] = useState("");
  const [profileSearch, setProfileSearch] = useState("");
  const [profileSearchMessage, setProfileSearchMessage] = useState("");
  const [profileSearchResults, setProfileSearchResults] = useState<UserSearchResult[]>([]);
  const [isProfileSearchOpen, setIsProfileSearchOpen] = useState(false);
  const [viewedIdentifier, setViewedIdentifier] = useState("");
  const [viewedRecords, setViewedRecords] = useState<BetRecord[]>([]);
  const [isAuthLoading, setIsAuthLoading] = useState(true);
  const [isProfileSearching, setIsProfileSearching] = useState(false);
  const [isSaving, setIsSaving] = useState(false);

  const canSave =
    form.teamLeft.trim() &&
    form.teamRight.trim() &&
    (form.selectedOutcome !== "draw" || form.hasDraw);
  const profileStats = calculateProfileStats(records);
  const viewedProfileStats = calculateProfileStats(viewedRecords);

  const loadRecords = useCallback(async (sessionToken: string) => {
    const { data, error } = await supabase.rpc("app_list_bets", {
      p_token: sessionToken,
    });

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
      const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);

      if (!sessionToken || (lastSeen && Date.now() - lastSeen > SESSION_MAX_IDLE_MS)) {
        localStorage.removeItem(LAST_SEEN_KEY);
        localStorage.removeItem(SESSION_TOKEN_KEY);
        if (isMounted) {
          setIsAuthLoading(false);
        }
        return;
      }

      const { data, error } = await supabase.rpc("app_restore_session", {
        p_token: sessionToken,
      });

      if (!isMounted) return;

      if (error || !data?.[0]) {
        localStorage.removeItem(LAST_SEEN_KEY);
        localStorage.removeItem(SESSION_TOKEN_KEY);
        setUser(null);
        setIsAuthLoading(false);
        return;
      }

      const restoredUser = {
        id: data[0].user_id,
        identifier: data[0].identifier,
      };

      setUser(restoredUser);
      localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
      await loadRecords(sessionToken);
      setIsAuthLoading(false);
    }

    initAuth();

    return () => {
      isMounted = false;
    };
  }, [loadRecords]);

  useEffect(() => {
    if (!user) {
      return;
    }

    const query = profileSearch.trim();
    if (!query) {
      return;
    }

    let isActive = true;
    const timeout = window.setTimeout(async () => {
      const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);
      if (!sessionToken) {
        if (isActive) {
          setProfileSearchMessage("Session หมดอายุ กรุณาเข้าสู่ระบบใหม่");
          setProfileSearchResults([]);
        }
        return;
      }

      setIsProfileSearching(true);

      const { data, error } = await supabase.rpc("app_search_users", {
        p_token: sessionToken,
        p_query: query,
      });

      if (!isActive) {
        return;
      }

      setIsProfileSearching(false);

      if (error) {
        setProfileSearchResults([]);
        setProfileSearchMessage(error.message);
        return;
      }

      const nextResults = data as UserSearchResult[];
      setProfileSearchResults(nextResults);
      setProfileSearchMessage("");
    }, 220);

    return () => {
      isActive = false;
      window.clearTimeout(timeout);
    };
  }, [profileSearch, user]);

  function updateForm(key: keyof BetFormState, value: string | boolean) {
    setForm((current) => {
      if (key === "hasDraw" && value === false && current.selectedOutcome === "draw") {
        return { ...current, hasDraw: false, oddsDraw: "", selectedOutcome: "left" };
      }

      if (
        typeof value === "string" &&
        (key === "oddsLeft" || key === "oddsDraw" || key === "oddsRight" || key === "stake") &&
        !isDecimalInput(value)
      ) {
        return current;
      }

      return { ...current, [key]: value };
    });
  }

  function updateProfileSearch(value: string) {
    setProfileSearch(value);
    setIsProfileSearchOpen(Boolean(value.trim()));

    if (!value.trim()) {
      setIsProfileSearching(false);
      setProfileSearchResults([]);
      setProfileSearchMessage("");
    }
  }

  async function handleLogin() {
    if (!username.trim() || !password) {
      setAuthMessage("กรอกชื่อผู้ใช้และรหัสผ่านก่อน");
      return;
    }

    setIsAuthLoading(true);
    setAuthMessage("");

    const { data, error } = await supabase.rpc("app_login", {
      p_identifier: username,
      p_password: password,
    });

    if (error || !data?.[0]) {
      setAuthMessage("ชื่อผู้ใช้หรือรหัสผ่านไม่ถูกต้อง ถ้ายังไม่มีบัญชีให้กดสมัคร");
      setIsAuthLoading(false);
      return;
    }

    const session = data[0];
    localStorage.setItem(SESSION_TOKEN_KEY, session.session_token);
    localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
    setUser({ id: session.user_id, identifier: session.identifier });
    await loadRecords(session.session_token);
    setIsAuthLoading(false);
  }

  async function handleSignUp() {
    if (!username.trim() || !password) {
      setAuthMessage("กรอกชื่อผู้ใช้และรหัสผ่านก่อนสมัคร");
      return;
    }

    setIsAuthLoading(true);
    setAuthMessage("");

    const { data, error } = await supabase.rpc("app_signup", {
      p_identifier: username,
      p_password: password,
    });

    if (error || !data?.[0]) {
      setAuthMessage(error?.message === "USER_ALREADY_EXISTS" ? "ชื่อผู้ใช้นี้มีอยู่แล้ว ให้กดเข้าสู่ระบบ" : error?.message || "สมัครไม่สำเร็จ");
      setIsAuthLoading(false);
      return;
    }

    const session = data[0];
    localStorage.setItem(SESSION_TOKEN_KEY, session.session_token);
    localStorage.setItem(LAST_SEEN_KEY, Date.now().toString());
    setUser({ id: session.user_id, identifier: session.identifier });
    await loadRecords(session.session_token);
    setIsAuthLoading(false);
  }

  async function handleLogout() {
    const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);
    if (sessionToken) {
      await supabase.rpc("app_logout", { p_token: sessionToken });
    }
    localStorage.removeItem(LAST_SEEN_KEY);
    localStorage.removeItem(SESSION_TOKEN_KEY);
    setUser(null);
    setRecords([]);
    setProfileSearch("");
    setProfileSearchMessage("");
    setProfileSearchResults([]);
    setIsProfileSearchOpen(false);
    setViewedIdentifier("");
    setViewedRecords([]);
  }

  async function loadViewedUserRecords(targetIdentifier: string) {
    setProfileSearch(targetIdentifier);
    setProfileSearchResults([]);
    setIsProfileSearchOpen(false);

    const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);
    if (!sessionToken) {
      setProfileSearchMessage("Session หมดอายุ กรุณาเข้าสู่ระบบใหม่");
      await handleLogout();
      return;
    }

    setIsProfileSearching(true);
    setProfileSearchMessage("");

    const { data, error } = await supabase.rpc("app_list_user_bets", {
      p_token: sessionToken,
      p_identifier: targetIdentifier,
    });

    setIsProfileSearching(false);

    if (error) {
      setProfileSearchMessage(error.message === "IDENTIFIER_REQUIRED" ? "พิมพ์ชื่อผู้ใช้ก่อนค้นหา" : error.message);
      return;
    }

    const nextRecords = (data as BetRecordRow[]).map(rowToRecord);
    setViewedIdentifier(targetIdentifier);
    setViewedRecords(nextRecords);
    setProfileSearchMessage("");
  }

  async function saveRecord() {
    if (!canSave || !user || isSaving) return;

    const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);
    if (!sessionToken) {
      setAuthMessage("Session หมดอายุ กรุณาเข้าสู่ระบบใหม่");
      await handleLogout();
      return;
    }

    setIsSaving(true);

    const { error } = await supabase.rpc("app_create_bet", {
      p_token: sessionToken,
      p_team_left: form.teamLeft.trim(),
      p_team_right: form.teamRight.trim(),
      p_has_draw: form.hasDraw,
      p_odds_left: parseDecimal(form.oddsLeft),
      p_odds_draw: form.hasDraw ? parseDecimal(form.oddsDraw) : null,
      p_odds_right: parseDecimal(form.oddsRight),
      p_selected_outcome: form.selectedOutcome,
      p_stake: parseDecimal(form.stake) ?? 0,
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
    await loadRecords(sessionToken);
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

  async function deleteRecord(record: BetRecord) {
    if (!user || record.userId !== user.id) {
      setAuthMessage("ลบได้เฉพาะบิลที่คุณสร้างเท่านั้น");
      return;
    }

    const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);
    if (!sessionToken) {
      setAuthMessage("Session หมดอายุ กรุณาเข้าสู่ระบบใหม่");
      await handleLogout();
      return;
    }

    const { error } = await supabase.rpc("app_delete_bet", {
      p_token: sessionToken,
      p_bet_id: record.id,
    });

    if (error) {
      setAuthMessage(error.message === "BET_NOT_FOUND_OR_NOT_OWNER" ? "ลบได้เฉพาะบิลที่คุณสร้างเท่านั้น" : error.message);
      return;
    }

    setRecords((current) => current.filter((currentRecord) => currentRecord.id !== record.id));
  }

  async function setRecordStatus(id: string, status: BetStatus) {
    const sessionToken = localStorage.getItem(SESSION_TOKEN_KEY);
    if (!sessionToken) {
      setAuthMessage("Session หมดอายุ กรุณาเข้าสู่ระบบใหม่");
      await handleLogout();
      return;
    }

    const { error } = await supabase.rpc("app_update_bet_status", {
      p_token: sessionToken,
      p_bet_id: id,
      p_status: status,
    });

    if (error) {
      setAuthMessage(error.message);
      return;
    }

    setRecords((current) => current.map((record) => (record.id === id ? { ...record, status } : record)));
  }

  if (isAuthLoading && !user) {
    return (
      <main className="grid min-h-screen place-items-center px-4 py-5 text-[#f4f7fb]">
        <div className="w-full max-w-[420px] rounded-[18px] border border-[#202a36] bg-[#18222e] p-5 text-center shadow-[0_18px_54px_rgba(0,0,0,0.48)]">
          <p className="text-sm font-bold text-[#7f8b9c]">กำลังตรวจสอบ session...</p>
        </div>
      </main>
    );
  }

  if (!user) {
    return (
      <main className="grid min-h-screen place-items-center px-4 py-5 text-[#f4f7fb]">
        <section className="w-full max-w-[420px] rounded-[18px] border border-[#202a36] bg-[#18222e] p-5 shadow-[0_18px_54px_rgba(0,0,0,0.48)]">
          <div className="mb-5">
            <p className="text-[11px] font-black uppercase tracking-[0.24em] text-[#7f8b9c]">Account</p>
            <h1 className="mt-1 text-2xl font-black tracking-tight">
              {authMode === "login" ? "เข้าสู่ระบบ" : "สมัครบัญชี"}
            </h1>
            <p className="mt-2 text-sm font-medium text-[#7f8b9c]">
              {authMode === "login" ? "ใช้ชื่อผู้ใช้หรืออีเมลที่สมัครไว้" : "ใช้อะไรก็ได้เป็นชื่อผู้ใช้ หรือใส่อีเมลจริงก็ได้"}
            </p>
          </div>

          <div className="space-y-4">
            <div className="grid grid-cols-2 gap-1.5 rounded-xl bg-[#0b111c] p-1.5">
              <button
                className={`rounded-xl px-4 py-3 text-sm font-black transition ${
                  authMode === "login" ? "bg-[#2a3542] text-white" : "text-[#7f8b9c] hover:bg-[#1b2531]"
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
                className={`rounded-xl px-4 py-3 text-sm font-black transition ${
                  authMode === "signup" ? "bg-[#2a3542] text-white" : "text-[#7f8b9c] hover:bg-[#1b2531]"
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
            {authMessage ? <p className="rounded-xl border border-[#ff5d7d]/35 bg-[#ff5d7d]/10 p-3 text-sm text-[#ffd4dd]">{authMessage}</p> : null}
            <button
              className="w-full rounded-xl bg-[#2a3542] px-5 py-4 text-base font-black text-white transition hover:bg-[#344252] disabled:cursor-not-allowed disabled:opacity-40"
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
    <main className="h-dvh overflow-hidden px-3 py-5 text-[#f4f7fb]">
      <div className="mx-auto flex max-h-full w-full max-w-[430px]">
        <section className="flex max-h-full w-full min-w-0 flex-col">
          <div className="block max-h-full">
            <div className="max-h-full min-w-0">
              <section className="flex max-h-full flex-col overflow-hidden rounded-[18px] border border-[#202a36] bg-[#18222e] shadow-[0_18px_54px_rgba(0,0,0,0.48)]">
                <div className="grid shrink-0 grid-cols-3 gap-1.5 border-b border-[#202a36] bg-[#0b111c] p-1.5">
                  <TabButton
                    active={activeTab === "create"}
                    icon={<Plus className="h-5 w-5" />}
                    label="ลงพนัน"
                    onClick={() => setActiveTab("create")}
                  />
                  <TabButton
                    active={activeTab === "records"}
                    icon={<ClipboardList className="h-5 w-5" />}
                    label={`ประวัติ (${records.length})`}
                    onClick={() => setActiveTab("records")}
                  />
                  <TabButton
                    active={activeTab === "profile"}
                    icon={<UserRound className="h-5 w-5" />}
                    label="โปรไฟล์"
                    onClick={() => setActiveTab("profile")}
                  />
                </div>

                <div className="min-h-0 flex-1 overflow-y-auto overscroll-contain">
                  {activeTab === "create" ? (
                    <div className="p-4">
                      <div className="mb-4">
                        <div className="min-w-0">
                          <p className="text-[11px] font-black uppercase tracking-[0.24em] text-[#7f8b9c]">Market Builder</p>
                          <h2 className="mt-1 text-xl font-black tracking-tight">สร้างคู่แข่งขัน</h2>
                          <p className="mt-1 text-xs font-medium text-[#7f8b9c]">กรอกทีม ค่าน้ำ และจำนวนเงินในหน้าเดียว</p>
                        </div>
                      </div>
                      {authMessage ? <p className="mb-4 rounded-xl border border-[#ff5d7d]/35 bg-[#ff5d7d]/10 p-3 text-sm text-[#ffd4dd]">{authMessage}</p> : null}

                      <div className="rounded-xl border border-[#202a36] bg-[#18222e] p-3 shadow-inner shadow-black/20">
                        <div className="grid grid-cols-[1fr_auto_1fr] items-end gap-3">
                          <TextField
                            label="ทีมซ้าย"
                            onChange={(value) => updateForm("teamLeft", value)}
                            placeholder="เช่น Arsenal"
                            value={form.teamLeft}
                          />
                          <div className="pb-4 text-center text-xs font-black text-[#566171]">VS</div>
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

                      <div className="mt-4 flex items-center justify-between gap-3 rounded-xl border border-[#202a36] bg-[#18222e] p-3 shadow-inner shadow-black/20">
                        <div>
                          <p className="font-black">ตลาด 1X2</p>
                          <p className="text-xs font-medium text-[#7f8b9c]">เปิดเสมอเมื่อรายการนี้มีราคา X</p>
                        </div>
                        <button
                          className={`rounded-xl px-4 py-2 text-sm font-black transition ${
                            form.hasDraw ? "bg-[#147f9f] text-white ring-1 ring-[#35b6e8]" : "bg-[#0b111c] text-[#b7c4d6]"
                          }`}
                          onClick={() => updateForm("hasDraw", !form.hasDraw)}
                          type="button"
                        >
                          {form.hasDraw ? "มีเสมอ" : "ไม่มีเสมอ"}
                        </button>
                      </div>

                      <div className="mt-4 rounded-xl border border-[#202a36] bg-[#18222e] p-3 shadow-inner shadow-black/20">
                        <div className="mb-3 flex items-center justify-between">
                          <p className="text-sm font-black text-[#f4f7fb]">Pick</p>
                          <p className="text-xs font-bold text-[#566171]">เลือก odds ที่ลง</p>
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
                          label="จำนวนเงิน (ไม่บังคับ)"
                          onChange={(value) => updateForm("stake", value)}
                          placeholder="1000"
                          type="number"
                          value={form.stake}
                        />
                      </div>

                      <button
                        className="mt-4 w-full rounded-xl bg-[#2a3542] px-5 py-4 text-base font-black text-white transition hover:bg-[#344252] disabled:cursor-not-allowed disabled:opacity-40"
                        disabled={!canSave || isSaving}
                        onClick={saveRecord}
                        type="button"
                      >
                        {isSaving ? "กำลังบันทึก..." : "Add to Bet Slip"}
                      </button>
                    </div>
                  ) : activeTab === "records" ? (
                    <div className="space-y-3 p-4">
                      {records.length ? (
                        records.map((record) => (
                          <BetCard
                            canDelete={record.userId === user.id}
                            key={record.id}
                            onCopy={() => copyRecord(record)}
                            onDelete={() => deleteRecord(record)}
                            onStatusChange={(status) => setRecordStatus(record.id, status)}
                            record={record}
                          />
                        ))
                      ) : (
                        <div className="rounded-xl border border-dashed border-[#2a3542] bg-[#0b111c] p-8 text-center text-[#b7c4d6]">
                          ยังไม่มีรายการ
                        </div>
                      )}
                    </div>
                  ) : (
                    <ProfilePanel
                      identifier={user.identifier}
                      isSearching={isProfileSearching}
                      onClearViewedUser={() => {
                        setProfileSearch("");
                        setProfileSearchResults([]);
                        setIsProfileSearchOpen(false);
                        setViewedIdentifier("");
                        setViewedRecords([]);
                        setProfileSearchMessage("");
                      }}
                      onLogout={handleLogout}
                      onSearchChange={updateProfileSearch}
                      onSelectUser={loadViewedUserRecords}
                      searchOpen={isProfileSearchOpen}
                      searchMessage={profileSearchMessage}
                      searchResults={profileSearchResults}
                      searchValue={profileSearch}
                      stats={profileStats}
                      viewedIdentifier={viewedIdentifier}
                      viewedRecords={viewedRecords}
                      viewedStats={viewedProfileStats}
                    />
                  )}
                </div>
              </section>
            </div>

          </div>
        </section>
      </div>
    </main>
  );
}

function ProfilePanel({
  identifier,
  isSearching,
  onClearViewedUser,
  onLogout,
  onSearchChange,
  onSelectUser,
  searchOpen,
  searchMessage,
  searchResults,
  searchValue,
  stats,
  viewedIdentifier,
  viewedRecords,
  viewedStats,
}: {
  identifier: string;
  isSearching: boolean;
  onClearViewedUser: () => void;
  onLogout: () => void;
  onSearchChange: (value: string) => void;
  onSelectUser: (identifier: string) => void;
  searchOpen: boolean;
  searchMessage: string;
  searchResults: UserSearchResult[];
  searchValue: string;
  stats: ProfileStats;
  viewedIdentifier: string;
  viewedRecords: BetRecord[];
  viewedStats: ProfileStats;
}) {
  const profitClass = stats.netProfit >= 0 ? "text-[#c9ffd8]" : "text-[#ffd4dd]";
  const viewedProfitClass = viewedStats.netProfit >= 0 ? "text-[#c9ffd8]" : "text-[#ffd4dd]";

  return (
    <div className="space-y-4 p-4">
      <section className="overflow-hidden rounded-xl border border-[#202a36] bg-[#18222e] p-4">
        <div className="flex items-start justify-between gap-3">
          <div className="min-w-0">
            <p className="text-[11px] font-black uppercase tracking-[0.24em] text-[#7f8b9c]">Profile</p>
            <h2 className="mt-1 truncate text-2xl font-black">{identifier}</h2>
            <p className="mt-2 text-sm font-medium text-[#7f8b9c]">สรุปผลงานจากรายการที่ปิดผลแล้ว</p>
          </div>
          <div className="flex shrink-0 flex-col items-end gap-2">
            <div className="rounded-xl border border-[#2a3542] bg-[#0b111c] p-3 text-[#b7c4d6]">
              <BarChart3 className="h-6 w-6" />
            </div>
            <button
              className="rounded-md border border-transparent bg-[#0b111c] px-3 py-1.5 text-xs font-black text-[#b7c4d6] transition hover:bg-[#111927] hover:text-[#f4f7fb]"
              onClick={onLogout}
              type="button"
            >
              ออก
            </button>
          </div>
        </div>
      </section>

      <section className="rounded-xl border border-[#202a36] bg-[#18222e] p-3 shadow-inner shadow-black/20">
        <div className="mb-3 flex items-center justify-between gap-3">
          <div>
            <p className="text-sm font-black text-[#f4f7fb]">ค้นหาคน</p>
            <p className="text-xs font-medium text-[#566171]">ดูโปรไฟล์และประวัติแบบอ่านอย่างเดียว</p>
          </div>
          {viewedIdentifier ? (
            <button
              className="rounded-md border border-transparent bg-[#0b111c] px-3 py-1.5 text-xs font-black text-[#b7c4d6] transition hover:bg-[#111927] hover:text-[#f4f7fb]"
              onClick={onClearViewedUser}
              type="button"
            >
              กลับของฉัน
            </button>
          ) : null}
        </div>
        <div className="relative">
          <label className="block">
            <span className="sr-only">ค้นหาชื่อผู้ใช้</span>
            <input
              className="w-full rounded-md border border-transparent bg-[#0b111c] py-3 pl-4 pr-11 text-sm font-bold text-[#f4f7fb] outline-none transition placeholder:text-[#3f4956] focus:border-[#5e6674]"
              onChange={(event) => onSearchChange(event.target.value)}
              placeholder="พิมพ์ชื่อผู้ใช้บางส่วน"
              value={searchValue}
            />
          </label>
          <Search className="pointer-events-none absolute right-4 top-1/2 h-4 w-4 -translate-y-1/2 text-[#7f8b9c]" />
          {searchOpen && searchValue.trim() ? (
            <div className="absolute left-0 right-0 top-[calc(100%+8px)] z-20 overflow-hidden rounded-xl border border-[#2a3542] bg-[#0b111c] shadow-2xl shadow-black/50">
              {isSearching ? (
                <div className="p-3 text-sm font-bold text-[#7f8b9c]">กำลังค้นหา...</div>
              ) : searchResults.length ? (
                searchResults.map((result) => (
                  <button
                    className="flex w-full items-center justify-between gap-3 px-4 py-3 text-left text-sm font-bold text-[#f4f7fb] transition hover:bg-[#111927]"
                    key={result.identifier}
                    onClick={() => onSelectUser(result.identifier)}
                    type="button"
                  >
                    <span className="truncate">{result.identifier}</span>
                    <span className="shrink-0 rounded-md bg-[#18222e] px-2.5 py-1 text-[11px] font-black text-[#7f8b9c]">
                      {formatNumber(result.record_count, 0)} บิล
                    </span>
                  </button>
                ))
              ) : (
                <div className="p-3 text-sm font-bold text-[#7f8b9c]">ไม่พบชื่อนี้</div>
              )}
            </div>
          ) : null}
        </div>
        {searchMessage ? <p className="mt-3 rounded-lg border border-[#2a3542] bg-[#0b111c] p-3 text-xs font-bold text-[#b7c4d6]">{searchMessage}</p> : null}
      </section>

      {viewedIdentifier ? (
        <section className="space-y-3 rounded-xl border border-[#202a36] bg-[#18222e] p-3 shadow-inner shadow-black/20">
          <div className="flex items-center justify-between gap-3">
            <div className="min-w-0">
              <p className="text-[11px] font-black uppercase tracking-[0.18em] text-[#566171]">Viewing</p>
              <h3 className="mt-1 truncate text-xl font-black">{viewedIdentifier}</h3>
            </div>
            <span className="rounded-xl border border-transparent bg-[#0b111c] px-3 py-2 text-xs font-black text-[#b7c4d6]">
              {formatNumber(viewedStats.totalRecords, 0)} บิล
            </span>
          </div>

          <div className="grid grid-cols-2 gap-3">
            <MiniStat label="อัตราชนะ" value={`${formatNumber(viewedStats.winRate, 1)}%`} />
            <MiniStat label="ทั้งหมด" value={formatNumber(viewedStats.totalRecords, 0)} />
            <MiniStat label="ชนะ" value={formatNumber(viewedStats.winCount, 0)} />
            <MiniStat label="แพ้" value={formatNumber(viewedStats.lostCount, 0)} />
          </div>

          <div className="rounded-xl border border-transparent bg-[#0b111c] p-3">
            <p className="text-[11px] font-black uppercase tracking-[0.18em] text-[#566171]">กำไรสุทธิ</p>
            <p className={`mt-1 text-2xl font-black ${viewedProfitClass}`}>{formatSignedAmount(viewedStats.netProfit)}</p>
          </div>

          {viewedRecords.length ? (
            <div className="space-y-3">
              {viewedRecords.map((record) => (
                <BetCard
                  canDelete={false}
                  key={record.id}
                  onCopy={() => {}}
                  onDelete={() => {}}
                  onStatusChange={() => {}}
                  preview
                  record={record}
                />
              ))}
            </div>
          ) : (
            <div className="rounded-xl border border-dashed border-[#2a3542] bg-[#0b111c] p-6 text-center text-sm font-bold text-[#b7c4d6]">
              ไม่พบรายการของ {viewedIdentifier} หรือยังไม่มีบิล
            </div>
          )}
        </section>
      ) : null}

      {!viewedIdentifier ? (
        <>
          <div className="grid grid-cols-2 gap-3">
            <StatCard label="อัตราชนะ" value={`${formatNumber(stats.winRate, 1)}%`} />
            <StatCard label="ทั้งหมด" value={formatNumber(stats.totalRecords, 0)} />
            <StatCard label="ชนะ" tone="win" value={formatNumber(stats.winCount, 0)} />
            <StatCard label="แพ้" tone="loss" value={formatNumber(stats.lostCount, 0)} />
          </div>

          <section className="rounded-xl border border-[#202a36] bg-[#18222e] p-4 shadow-inner shadow-black/20">
            <div className="mb-3 flex items-center justify-between gap-3">
              <div>
                <p className="text-sm font-black text-[#f4f7fb]">ค่าน้ำและเงิน</p>
                <p className="text-xs font-medium text-[#566171]">คิดเฉพาะรายการชนะ/แพ้ ไม่รวมรอผลและคืนทุน</p>
              </div>
              <span className="rounded-xl border border-transparent bg-[#0b111c] px-3 py-2 text-xs font-black text-[#b7c4d6]">
                ปิดผล {formatNumber(stats.settledCount, 0)}
              </span>
            </div>

            <div className="grid grid-cols-2 gap-3">
              <MiniStat label="ลงเท่ากันทุกไม้" value={`${formatSignedAmount(stats.unitNetProfit)}u (${formatSignedAmount(stats.unitRoi)}%)`} />
              <MiniStat label="เงินลงรวม" value={formatNumber(stats.totalStake)} />
              <MiniStat label="ยอดรับตอนชนะ" value={formatNumber(stats.grossReturn)} />
              <MiniStat label="รอผล / คืนทุน" value={`${formatNumber(stats.pendingCount, 0)} / ${formatNumber(stats.voidCount, 0)}`} />
            </div>

            <div className="mt-3 rounded-xl border border-transparent bg-[#0b111c] p-3">
              <p className="text-[11px] font-black uppercase tracking-[0.18em] text-[#566171]">กำไรสุทธิ</p>
              <p className={`mt-1 text-2xl font-black ${profitClass}`}>{formatSignedAmount(stats.netProfit)}</p>
            </div>
          </section>

          <section className="rounded-xl border border-[#202a36] bg-[#18222e] p-4 text-sm text-[#b7c4d6] shadow-inner shadow-black/20">
            <p className="font-black text-[#f4f7fb]">สูตรค่าน้ำที่ใช้</p>
            <p className="mt-2">
              ถ้าชนะน้ำ 1.90 จะนับเป็น +0.90 หน่วย เพราะได้คืน 1.90 แต่เงินต้นคือ 1 หน่วย
            </p>
            <p className="mt-2">ถ้าแพ้จะนับ -1.00 หน่วยเต็ม แล้วเอาทุกบิลมารวมเพื่อดูว่ากลยุทธ์ย้อนหลังบวกหรือลบกี่ %</p>
          </section>
        </>
      ) : null}
    </div>
  );
}

function StatCard({ label, tone = "default", value }: { label: string; tone?: "default" | "loss" | "win"; value: string }) {
  const toneClass =
    tone === "win"
      ? "border-[#54e57c]/30 bg-[#54e57c]/10 text-[#c9ffd8]"
      : tone === "loss"
        ? "border-[#ff5d7d]/30 bg-[#ff5d7d]/10 text-[#ffd4dd]"
        : "border-[#202a36] bg-[#18222e] text-[#f4f7fb]";

  return (
    <div className={`rounded-xl border p-4 shadow-lg shadow-black/20 ${toneClass}`}>
      <p className="text-[11px] font-black uppercase tracking-[0.18em] opacity-60">{label}</p>
      <p className="mt-2 text-2xl font-black">{value}</p>
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
      className={`inline-flex items-center justify-center gap-2 rounded-xl px-4 py-3 text-sm font-black transition ${
        active ? "bg-[#2a3542] text-white" : "text-[#7f8b9c] hover:bg-[#1b2531] hover:text-[#f4f7fb]"
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
      <span className="mb-2 block text-[13px] font-bold text-[#7f8b9c]">{label}</span>
      <input
        className="w-full rounded-md border border-transparent bg-[#0b111c] px-4 py-3 text-base font-bold text-[#f4f7fb] outline-none transition placeholder:text-[#3f4956] focus:border-[#5e6674] focus:bg-[#0b111c] disabled:opacity-30"
        disabled={disabled}
        inputMode={type === "number" ? "decimal" : "text"}
        onChange={(event) => onChange(event.target.value)}
        placeholder={placeholder}
        type={type === "number" ? "text" : type}
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
          ? "border-[#35b6e8] bg-[#147f9f] text-white"
          : "border-transparent bg-[#0b111c] text-[#f4f7fb] hover:bg-[#111927]"
      }`}
      onClick={onClick}
      type="button"
    >
      <p className={`truncate text-xs font-black uppercase tracking-wide ${active ? "text-white/70" : "text-[#7f8b9c]"}`}>{label}</p>
      <p className={`mt-1 text-xl font-black ${active ? "text-white" : "text-[#f4f7fb]"}`}>{odds || "-"}</p>
    </button>
  );
}

function BetCard({
  canDelete,
  onCopy,
  onDelete,
  onStatusChange,
  preview = false,
  record,
}: {
  canDelete: boolean;
  onCopy: () => void;
  onDelete: () => void;
  onStatusChange: (status: BetStatus) => void;
  preview?: boolean;
  record: BetRecord;
}) {
  const status = statusConfig[record.status];
  const statusBarClass =
    record.status === "won"
      ? "bg-[#54e57c]"
      : record.status === "lost"
        ? "bg-[#ff5d7d]"
        : "bg-[#5e6674]";

  return (
    <article className="relative overflow-hidden rounded-xl border border-[#202a36] bg-[#18222e] p-3 pl-5 shadow-lg shadow-black/25">
      <div className={`absolute bottom-0 left-0 top-0 w-1.5 ${statusBarClass}`} />
      <div className="flex flex-wrap items-start justify-between gap-3">
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <span className={`inline-flex items-center gap-1 rounded-md border px-2.5 py-1 text-[11px] font-black ${status.className}`}>
              {status.icon}
              {status.label}
            </span>
          </div>
          <h3 className="mt-3 truncate text-base font-black">
            {record.teamLeft} <span className="text-[#566171]">vs</span> {record.teamRight}
          </h3>
          <p className="mt-1 text-xs font-semibold text-[#566171]">{record.createdAt}</p>
        </div>

        <div className="flex shrink-0 flex-col items-end gap-2">
          <div className="inline-flex items-center gap-1.5 rounded-md border border-transparent bg-[#0b111c] px-2.5 py-1 text-[11px] font-black text-[#f4f7fb]">
            <span className="uppercase tracking-[0.16em] text-[#7f8b9c]/70">Stake</span>
            <span>{formatAmount(record.stake)}</span>
          </div>
          {!preview ? (
            <div className="flex gap-2">
              <IconButton label="คัดลอก" onClick={onCopy}>
                <Copy className="h-4 w-4" />
              </IconButton>
              {canDelete ? (
                <IconButton label="ลบ" onClick={onDelete}>
                  <Trash2 className="h-4 w-4" />
                </IconButton>
              ) : null}
            </div>
          ) : null}
        </div>
      </div>

      <div className="mt-3 grid grid-cols-3 gap-2 rounded-xl bg-[#18222e]">
        <MiniStat active={record.selectedOutcome === "left"} label={record.teamLeft || "ซ้าย"} value={record.oddsLeft || "-"} />
        <MiniStat
          active={record.selectedOutcome === "draw"}
          label="เสมอ"
          muted={!record.hasDraw}
          value={record.hasDraw ? record.oddsDraw || "-" : "-"}
        />
        <MiniStat active={record.selectedOutcome === "right"} label={record.teamRight || "ขวา"} value={record.oddsRight || "-"} />
      </div>

      {!preview && record.status === "pending" ? (
        <div className="mt-3 grid grid-cols-2 gap-2">
          <button
            className="rounded-md border border-transparent bg-[#0b111c] px-3 py-2 text-xs font-black text-[#b7c4d6] transition hover:bg-[#111927]"
            onClick={() => onStatusChange("won")}
            type="button"
          >
            ชนะ
          </button>
          <button
            className="rounded-md border border-transparent bg-[#0b111c] px-3 py-2 text-xs font-black text-[#b7c4d6] transition hover:bg-[#111927]"
            onClick={() => onStatusChange("lost")}
            type="button"
          >
            แพ้
          </button>
        </div>
      ) : null}

    </article>
  );
}

function MiniStat({
  active = false,
  label,
  muted = false,
  value,
}: {
  active?: boolean;
  label: string;
  muted?: boolean;
  value: string;
}) {
  return (
    <div
      className={`min-w-0 rounded-lg border p-2.5 transition ${
        active ? "border-[#35b6e8] bg-[#147f9f] text-white" : "border-transparent bg-[#0b111c] text-[#f4f7fb]"
      } ${muted ? "opacity-35" : ""}`}
    >
      <p className={`truncate text-[11px] font-semibold ${active ? "text-white/70" : "text-[#7f8b9c]"}`}>{label}</p>
      <p className="mt-1 truncate text-sm font-black">{value}</p>
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
      className="rounded-md border border-transparent bg-[#0b111c] p-2.5 text-[#b7c4d6] transition hover:bg-[#111927]"
      onClick={onClick}
      type="button"
    >
      {children}
    </button>
  );
}

