"use client";

import {
  Activity, ArrowDownLeft, ArrowRight, ArrowUpRight, Bell, Bot, CalendarDays, Check, ChevronLeft, Eye,
  ChevronRight, CircleHelp, CreditCard, FileCheck2, FilePlus2, FileText,
  LayoutDashboard, LogOut, Menu, Minus, Plus, Search, Settings2, ShieldCheck, Sparkles,
  Upload, Users, Wallet, X, AlertCircle, ClipboardList, BarChart2, UserPlus, Key,
} from "lucide-react";
import type { LucideIcon } from "lucide-react";
import Image from "next/image";
import type { ChangeEvent, FormEvent } from "react";
import { useCallback, useEffect, useRef, useState } from "react";
import "./budget.css";

const API = "/api/v1";
const DIRECT_API = process.env.NEXT_PUBLIC_API_BASE_URL || "http://localhost:8000/api/v1";
type View = "Dashboard" | "Documents" | "Expenses" | "Budget" | "Reimbursements" | "Users" | "Settings" | "MyClaims" | "Categories" | "SubmitClaim";
type UploadStage = "drop" | "uploading" | "processing" | "review" | "duplicate" | "failed";
type UserRole = "admin" | "user";
type User = { id: string; email: string; display_name: string; employee_id?: string | null; user_role: UserRole; must_change_password?: boolean };
type ChatMessage = { role: "user" | "assistant"; content: string };
type Expense = { id: string; merchant_name?: string; description?: string; invoice_number?: string; expense_date?: string; total_amount: string; currency: string; status?: string; category?: string };
type ExpenseCategory = "Groceries & Dining" | "Transportation" | "Shopping & Retail" | "Bills & Utilities" | "Housing" | "Healthcare" | "Travel" | "Education" | "Business" | "Entertainment" | "Taxes & Fees" | "Other";
const expenseCategories: ExpenseCategory[] = ["Groceries & Dining", "Transportation", "Shopping & Retail", "Bills & Utilities", "Housing", "Healthcare", "Travel", "Education", "Business", "Entertainment", "Taxes & Fees", "Other"];
type ManualExpense = { merchant: string; location: string; description: string; date: string; amount: string; currency: string; category: ExpenseCategory };
type Budget = {
  id: string;
  period_type: "quarter" | "half_year" | "year";
  period_index: number;
  year: number;
  title: string;
  start_date: string;
  end_date: string;
  currency: string;
  amount: string;
  expense_amount: string;
  remaining_amount: string;
};
type ReimbursementCategory = {
  id: string;
  team_id: string;
  name: string;
  description: string | null;
  max_amount: string;
  currency: string;
  is_active: boolean;
  created_at: string;
  created_by: string | null;
};
type ReimbursementClaim = {
  id: string;
  expense_id: string | null;
  category_id: string | null;
  employee_id: string;
  employee_name: string;
  employee_email: string;
  merchant_name: string;
  expense_date: string | null;
  description: string;
  category: string | null;
  amount: string;
  currency: string;
  reason: string;
  status: "submitted" | "approved" | "rejected" | "paid";
  review_note: string | null;
  reviewer_name: string | null;
  submitted_at: string;
  reviewed_at: string | null;
  paid_at: string | null;
};
type ClaimLimitCheck = {
  category_id: string;
  category_name: string;
  max_amount: string;
  currency: string;
  claimed_this_period: string;
  remaining_amount: string;
  period_type: string;
  period_start: string;
  period_end: string;
  can_claim: boolean;
  message: string | null;
};
type ReimbursementWorkspace = {
  team: { id: string; name: string; role: "owner" | "employee" } | null;
  members: Array<{ id: string; display_name: string; email: string; employee_id: string | null; role: string; must_change_password?: boolean; created_at?: string }>;
  items: ReimbursementClaim[];
};
type Document = { id: string; filename: string; status: string; stage?: string; created_at: string; error_code?: string; error_message?: string; extraction?: Invoice; deleted_at?: string };
type DocumentDetails = Invoice & { expense_saved: boolean };
type InvoiceLine = { line_key?: string; description: string; category?: ExpenseCategory | null; hsn_sac_code?: string | null; quantity?: string | null; unit?: string | null; unit_price?: string | null; discount?: string | null; taxable_amount?: string | null; gst_rate?: string | null; cgst?: string | null; sgst?: string | null; igst?: string | null; cess?: string | null; line_total?: string | null };
type Invoice = {
  document_type?: string; invoice_number?: string | null; invoice_date?: string | null; due_date?: string | null;
  currency?: string; seller_name?: string | null; buyer_name?: string | null; seller_gstin?: string | null;
  buyer_gstin?: string | null; billing_address?: string | null; shipping_address?: string | null;
  place_of_supply?: string | null; payment_terms?: string | null; subtotal?: string | null; discount_total?: string | null;
  taxable_value?: string | null; cgst?: string | null; sgst?: string | null; igst?: string | null; cess?: string | null;
  other_charges?: string | null; round_off?: string | null; total?: string | null; category?: ExpenseCategory;
  line_items?: InvoiceLine[];
  warnings?: string[];
};
type Overview = { expenses: string; expense_count: number; currency: string; currency_totals?: Array<{ currency: string; total: string }>; monthly?: Array<{ month: string; total: string }>; merchants?: Array<{ name: string; total: string }>; category_totals?: Array<{ category: string; currency: string; total: string; count: number }>; uncategorized_count?: number };
class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
    this.name = "ApiError";
  }
}
async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API}${path}`, { ...init, credentials: "include", headers: { ...(init?.body instanceof FormData ? {} : { "Content-Type": "application/json" }), ...init?.headers } });
  const body = await response.json().catch(() => ({}));
  if (!response.ok) throw new ApiError(
    typeof body.detail === "string"
      ? body.detail
      : Array.isArray(body.detail)
        ? body.detail.map((issue: { msg?: string }) => issue.msg).filter(Boolean).join(" ") || `Request failed (${response.status})`
        : body.message || `Request failed (${response.status})`,
    response.status,
  );
  return body as T;
}
function money(value?: string | number | null, currency = "INR") {
  if (value == null || value === "") return "—";
  return new Intl.NumberFormat("en-IN", { style: "currency", currency, maximumFractionDigits: 0 }).format(Number(value));
}
function reimbursementMoney(value: string, currency: string) {
  return new Intl.NumberFormat("en-IN", {
    style: "currency",
    currency,
    minimumFractionDigits: 2,
    maximumFractionDigits: 2,
  }).format(Number(value));
}
function date(value?: string) {
  return value ? new Intl.DateTimeFormat("en-IN", { day: "numeric", month: "short", year: "numeric" }).format(new Date(value)) : "—";
}
function dateInputValue(value: Date) {
  const year = value.getFullYear();
  const month = String(value.getMonth() + 1).padStart(2, "0");
  const day = String(value.getDate()).padStart(2, "0");
  return `${year}-${month}-${day}`;
}
function monthInputOffset(monthsAgo: number) {
  const value = new Date();
  value.setDate(1);
  value.setMonth(value.getMonth() - monthsAgo);
  return dateInputValue(value);
}
function renderUploadErrors(message: string) {
  return message.split("\n").map((line, index) => {
    const uploadMatch = /^(.*): This file matches existing upload: (.+)\.$/.exec(line);
    const processingMatch = /^This upload matches existing file: (.+)\.$/.exec(line);
    const duplicate = /^(.*): This file has already been uploaded\.$/.exec(line);
    return (
      <span className="upload-error-line" key={`${index}-${line}`}>
        {uploadMatch
          ? <>{uploadMatch[1]}: This file matches existing upload: <strong className="upload-error-filename">{uploadMatch[2]}</strong>.</>
          : processingMatch
            ? <>This upload matches existing file: <strong className="upload-error-filename">{processingMatch[1]}</strong>.</>
            : duplicate
          ? <><strong className="upload-error-filename">{duplicate[1]}</strong>: This file has already been uploaded.</>
          : line}
      </span>
    );
  });
}

const adminNav = [
  { name: "Dashboard" as const, icon: LayoutDashboard },
  { name: "Budget" as const, icon: Wallet },
  { name: "Expenses" as const, icon: CreditCard },
  { name: "Documents" as const, icon: FileText, badge: true },
  { name: "Reimbursements" as const, icon: Wallet },
  { name: "Categories" as const, icon: ClipboardList },
  { name: "Users" as const, icon: Users },
  { name: "Settings" as const, icon: Settings2 },
];

const userNav = [
  { name: "Dashboard" as const, icon: LayoutDashboard },
  { name: "MyClaims" as const, icon: ClipboardList },
  { name: "SubmitClaim" as const, icon: FilePlus2 },
  { name: "Expenses" as const, icon: CreditCard },
  { name: "Documents" as const, icon: FileText, badge: true },
  { name: "Settings" as const, icon: Settings2 },
];

export default function HomePage() {
  const [user, setUser] = useState<User | null>(null);
  const [view, setView] = useState<View>("Dashboard");
  const [overview, setOverview] = useState<Overview | null>(null);
  const [expenses, setExpenses] = useState<Expense[]>([]);
  const [budgets, setBudgets] = useState<Budget[]>([]);
  const [documents, setDocuments] = useState<Document[]>([]);
  const [reimbursementWorkspace, setReimbursementWorkspace] = useState<ReimbursementWorkspace | null>(null);
  const [categories, setCategories] = useState<ReimbursementCategory[]>([]);
  const [authMode, setAuthMode] = useState<"login" | "register">("login");
  const [authEmail, setAuthEmail] = useState("");
  const [authPassword, setAuthPassword] = useState("");
  const [authName, setAuthName] = useState("");
  const [authBusy, setAuthBusy] = useState(false);
  const [authError, setAuthError] = useState("");
  const [passwordChange, setPasswordChange] = useState("");
  const [passwordChangeError, setPasswordChangeError] = useState("");
  const [passwordChangeBusy, setPasswordChangeBusy] = useState(false);
  const [loadError, setLoadError] = useState("");
  const [busy, setBusy] = useState(false);
  const [categoryAnalysisBusy, setCategoryAnalysisBusy] = useState(false);
  const [toast, setToast] = useState("");
  const [uploadOpen, setUploadOpen] = useState(false);
  const [uploadStage, setUploadStage] = useState<UploadStage>("drop");
  const [uploadError, setUploadError] = useState("");
  const [uploadProgressLabel, setUploadProgressLabel] = useState("");
  const [uploadDocumentId, setUploadDocumentId] = useState<string | null>(null);
  const [reviewDoc, setReviewDoc] = useState<(Document & { previewUrl?: string }) | null>(null);
  const [documentDetails, setDocumentDetails] = useState<{ document: Document; details: DocumentDetails } | null>(null);
  const [documentDetailsLoading, setDocumentDetailsLoading] = useState(false);
  const [question, setQuestion] = useState("");
  const [chatMessages, setChatMessages] = useState<ChatMessage[]>([]);
  const [answerBusy, setAnswerBusy] = useState(false);
  const [chatOpen, setChatOpen] = useState(false);
  const [showStarkPrompt, setShowStarkPrompt] = useState(true);
  const chatEndRef = useRef<HTMLDivElement>(null);
  const [mobileNav, setMobileNav] = useState(false);

  const refreshData = useCallback(async () => {
    if (!user) return;
    setLoadError("");
    const results = await Promise.allSettled([
      request<Overview>("/analytics/overview"),
      request<{ items: Expense[] }>("/expenses?limit=100"),
      request<{ items: Document[] }>("/documents?limit=100"),
      request<{ items: Budget[] }>("/budgets"),
      request<ReimbursementWorkspace>("/reimbursements"),
    ]);
    if (results.some((result) => result.status === "rejected" && result.reason instanceof ApiError && result.reason.status === 401)) {
      setUser(null);
      setOverview(null);
      setExpenses([]);
      setDocuments([]);
      setBudgets([]);
      setReimbursementWorkspace(null);
      setCategories([]);
      setLoadError("");
      return;
    }
    if (results[0].status === "fulfilled") setOverview(results[0].value);
    else setLoadError(results[0].reason instanceof Error ? results[0].reason.message : "Could not load overview.");
    if (results[1].status === "fulfilled") setExpenses(results[1].value.items || []);
    if (results[2].status === "fulfilled") setDocuments(results[2].value.items || []);
    if (results[3].status === "fulfilled") setBudgets(results[3].value.items || []);
    if (results[4].status === "fulfilled") setReimbursementWorkspace(results[4].value);
    else if (results[0].status === "fulfilled") {
      setLoadError(results[4].reason instanceof Error ? results[4].reason.message : "Could not load reimbursements.");
    }
    
    if (user.user_role === "admin") {
      try {
        const catResponse = await request<{ items: ReimbursementCategory[] }>("/reimbursements/categories/all");
        setCategories(catResponse.items || []);
      } catch {
        setCategories([]);
      }
    }
  }, [user]);

  useEffect(() => {
    setChatMessages([]);
    setQuestion("");
  }, [user?.id]);

  useEffect(() => {
    if (chatOpen) chatEndRef.current?.scrollIntoView({ behavior: "smooth", block: "end" });
  }, [chatMessages, answerBusy, chatOpen]);

  useEffect(() => {
    let active = true;
    request<User>("/auth/me").then((u) => { if (active) setUser(u); }).catch(() => {});
    return () => { active = false; };
  }, []);
  useEffect(() => { refreshData(); }, [refreshData]);
  useEffect(() => {
    if (!user) return;
    const pending = documents.filter((d) => ["queued", "processing"].includes(d.status));
    if (!pending.length) return;
    const timer = window.setInterval(() => {
      pending.forEach(async (doc) => {
        try {
          const updated = await request<Document>(`/documents/${doc.id}/status`);
          setDocuments((list) => list.map((item) => item.id === doc.id ? { ...item, ...updated } : item));
          if (updated.status === "review") {
            setToast("A document is ready for review.");
            if (updated.id === uploadDocumentId) setUploadStage("review");
            refreshData();
          } else if (updated.status === "failed" && updated.error_code === "DUPLICATE_INVOICE") {
            setToast(updated.error_message || "This invoice already exists. The uploaded file was not added again.");
            if (updated.id === uploadDocumentId) setUploadStage("duplicate");
            refreshData();
          } else if (updated.status === "failed" && updated.id === uploadDocumentId) {
            setUploadStage("failed");
            setToast(updated.error_message || "Document processing failed.");
            refreshData();
          }
        } catch { /* The next poll will retry transient status failures. */ }
      });
    }, 3000);
    return () => window.clearInterval(timer);
  }, [user, documents, refreshData, uploadDocumentId]);
  useEffect(() => {
    const uploadedDocument = documents.find((document) => document.id === uploadDocumentId);
    if (!uploadedDocument) return;
    if (uploadedDocument.status === "review") setUploadStage("review");
    else if (uploadedDocument.status === "failed" && uploadedDocument.error_code === "DUPLICATE_INVOICE") setUploadStage("duplicate");
    else if (uploadedDocument.status === "failed") setUploadStage("failed");
  }, [documents, uploadDocumentId]);

  async function submitAuth(e: FormEvent) {
    e.preventDefault(); setAuthBusy(true); setAuthError("");
    try {
      const endpoint = authMode === "login" ? "/auth/login" : "/auth/register";
      const payload = authMode === "login" ? { email: authEmail, password: authPassword } : { email: authEmail, password: authPassword, display_name: authName };
      const u = await request<User>(endpoint, { method: "POST", body: JSON.stringify(payload) });
      setUser(u);
    } catch (err) { setAuthError(err instanceof Error ? err.message : "Could not sign in."); }
    finally { setAuthBusy(false); }
  }
  async function changeTemporaryPassword(event: FormEvent) {
    event.preventDefault();
    setPasswordChangeBusy(true);
    setPasswordChangeError("");
    try {
      await request("/auth/change-password", {
        method: "POST",
        body: JSON.stringify({ new_password: passwordChange }),
      });
      setUser((current) => current ? { ...current, must_change_password: false } : current);
      setPasswordChange("");
    } catch (err) {
      setPasswordChangeError(err instanceof Error ? err.message : "Could not change your password.");
    } finally {
      setPasswordChangeBusy(false);
    }
  }
  async function signOut() {
    try { await request("/auth/logout", { method: "POST" }); }
    catch (err) { setToast(err instanceof Error ? err.message : "Could not sign out."); return; }
    setUser(null); setOverview(null); setExpenses([]); setBudgets([]); setDocuments([]); setReimbursementWorkspace(null); setCategories([]);
  }
  async function createReimbursementTeam(name: string) {
    await request("/reimbursements/teams", {
      method: "POST",
      body: JSON.stringify({ name }),
    });
    await refreshData();
    setToast("Reimbursement team created.");
  }
  async function submitReimbursementClaim(expenseId: string, reason: string, categoryId?: string, claimAmount?: string, receiptFile?: File) {
    const body: Record<string, any> = { expense_id: expenseId, reason, category_id: categoryId };
    if (claimAmount) body.claim_amount = claimAmount;
    if (receiptFile) {
      body.receipt_filename = receiptFile.name;
      body.receipt_content_type = receiptFile.type;
    }
    await request("/reimbursements/claims", {
      method: "POST",
      body: JSON.stringify(body),
    });
    await refreshData();
    setToast("Reimbursement claim submitted.");
  }
  async function checkClaimLimit(expenseId: string, categoryId: string, claimAmount?: string) {
    const body: Record<string, any> = { expense_id: expenseId, category_id: categoryId, reason: "Checking limit" };
    if (claimAmount) body.claim_amount = claimAmount;
    const result = await request<ClaimLimitCheck>("/reimbursements/claims/check-limit", {
      method: "POST",
      body: JSON.stringify(body),
    });
    return result;
  }
  async function requestCategory(name: string, description: string) {
    await request("/reimbursements/categories/request", {
      method: "POST",
      body: JSON.stringify({ name, description }),
    });
    await refreshData();
    setToast("Category request submitted to admin.");
  }
  async function decideReimbursementClaim(claimId: string, action: "approve" | "reject", note: string) {
    await request(`/reimbursements/claims/${claimId}/decision`, {
      method: "PATCH",
      body: JSON.stringify({ action, note }),
    });
    await refreshData();
    setToast(action === "approve" ? "Claim approved." : "Claim rejected.");
  }
  async function markReimbursementClaimPaid(claimId: string) {
    await request(`/reimbursements/claims/${claimId}/paid`, { method: "POST" });
    await refreshData();
    setToast("Claim marked as paid.");
  }
  async function createCategory(payload: { name: string; description?: string; max_amount: string; currency: string }) {
    await request("/reimbursements/categories", {
      method: "POST",
      body: JSON.stringify(payload),
    });
    await refreshData();
    setToast("Category created.");
  }
  async function updateCategory(categoryId: string, payload: { name?: string; description?: string; max_amount?: string; currency?: string; is_active?: boolean }) {
    await request(`/reimbursements/categories/${categoryId}`, {
      method: "PATCH",
      body: JSON.stringify(payload),
    });
    await refreshData();
    setToast("Category updated.");
  }
  async function deleteCategory(categoryId: string) {
    await request(`/reimbursements/categories/${categoryId}`, { method: "DELETE" });
    await refreshData();
    setToast("Category deleted.");
  }
  async function exportCsv() {
    try {
      const response = await fetch(`${API}/analytics/export.csv`, { credentials: "include" });
      if (!response.ok) {
        const body = await response.json().catch(() => ({}));
        throw new Error(body.detail || `Export failed (${response.status})`);
      }
      const downloadUrl = URL.createObjectURL(await response.blob());
      const link = window.document.createElement("a");
      link.href = downloadUrl;
      link.download = "xpenziq-financial-records.csv";
      link.click();
      URL.revokeObjectURL(downloadUrl);
      setToast("Your financial records were exported.");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not export financial records.");
    }
  }
  async function uploadFiles(files: File[]) {
    if (!files.length) return;
    setBusy(true);
    setUploadStage("uploading");
    setUploadError("");
    const failures: string[] = [];
    let accepted = 0;
    try {
      for (const [index, file] of files.entries()) {
        setUploadStage("uploading");
        setUploadProgressLabel(`Uploading ${index + 1} of ${files.length}: ${file.name}`);
        const form = new FormData();
        form.append("file", file);
        try {
          const uploadedDocument = await request<Document>("/documents/upload", { method: "POST", body: form });
          setUploadDocumentId(uploadedDocument.id);
          accepted++;
        } catch (err) {
          failures.push(`${file.name}: ${err instanceof Error ? err.message : "Upload failed."}`);
        }
      }
      await refreshData();
      if (accepted) {
        setUploadStage("processing");
        setUploadProgressLabel(`${accepted} file${accepted === 1 ? "" : "s"} accepted for processing.`);
        setToast(`${accepted} file${accepted === 1 ? "" : "s"} uploaded${failures.length ? `; ${failures.length} could not be uploaded` : ""}.`);
      } else {
        setUploadStage("drop");
      }
      if (failures.length) {
        const failureSummary = failures.join("\n");
        setUploadError(failureSummary);
        setToast(failureSummary);
      }
    }
    finally { setBusy(false); }
  }
  async function saveManualExpense(expense: ManualExpense) {
    setBusy(true);
    try {
      const amount = expense.amount;
      await request("/expenses", {
        method: "POST",
        body: JSON.stringify({
          document_type: "other",
          invoice_date: expense.date,
          currency: expense.currency.toUpperCase(),
          seller_name: expense.merchant.trim(),
          place_of_supply: expense.location.trim() || null,
          total: amount,
          line_items: [{
            description: expense.description.trim(),
            category: expense.category,
            line_total: amount,
          }],
        }),
      });
      await refreshData();
      setUploadOpen(false);
      setUploadStage("drop");
      setUploadError("");
      setUploadDocumentId(null);
      setToast("Manual expense saved.");
    } finally {
      setBusy(false);
    }
  }
  async function analyzeExpenseCategories() {
    setCategoryAnalysisBusy(true);
    try {
      const result = await request<{ categorized: number; remaining: number }>("/analytics/categories/analyze", { method: "POST" });
      await refreshData();
      setToast(result.categorized
        ? `AI categorized ${result.categorized} line item${result.categorized === 1 ? "" : "s"}${result.remaining ? `. ${result.remaining} remaining.` : "."}`
        : "All line items are already categorized.");
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not analyze expense categories.");
    } finally {
      setCategoryAnalysisBusy(false);
    }
  }
  async function loadReview(doc: Document) {
    try {
      const isPdf = doc.filename.toLowerCase().endsWith(".pdf");
      const [data, preview] = await Promise.allSettled([
        request<Invoice>(`/documents/${doc.id}/extraction`),
        isPdf
          ? Promise.resolve(null)
          : fetch(`${API}/documents/${doc.id}/preview`, { credentials: "include" }).then(r => r.ok ? r.blob() : null),
      ]);
      const extraction = data.status === "fulfilled" ? data.value : undefined;
      const previewBlob = preview.status === "fulfilled" ? preview.value : null;
      if (extraction) {
        extraction.line_items = extraction.line_items?.map((line, index) => ({ ...line, line_key: `${index}-${line.description}` }));
      }
      const previewUrl = previewBlob ? URL.createObjectURL(previewBlob) : undefined;
      setReviewDoc({ ...doc, extraction, previewUrl });
    } catch (err) { setToast(err instanceof Error ? err.message : "Could not load extraction."); }
  }
  async function loadDocumentDetails(doc: Document) {
    setDocumentDetailsLoading(true);
    try {
      const details = await request<DocumentDetails>(`/documents/${doc.id}/details`);
      setDocumentDetails({ document: doc, details });
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not load document details.");
    } finally {
      setDocumentDetailsLoading(false);
    }
  }
  async function confirmReview() {
    if (!reviewDoc?.extraction) return;
    setBusy(true);
    try {
      if (reviewDoc.status === "new") {
        await request("/expenses", { method: "POST", body: JSON.stringify(reviewDoc.extraction) });
      } else if (reviewDoc.status === "editing") {
        await request(`/expenses/${reviewDoc.id}`, { method: "PATCH", body: JSON.stringify(reviewDoc.extraction) });
      } else {
        await request(`/documents/${reviewDoc.id}/confirm`, { method: "POST", body: JSON.stringify(reviewDoc.extraction) });
      }
      setReviewDoc(null); await refreshData(); setView("Expenses"); setToast(reviewDoc.status === "editing" ? "Expense changes saved." : "Expense confirmed and saved.");
    } catch (err) { setToast(err instanceof Error ? err.message : "Could not confirm invoice."); }
    finally { setBusy(false); }
  }
  async function editExpense(expense: Expense) {
    try {
      const extraction = await request<Invoice>(`/expenses/${expense.id}`);
      extraction.line_items = extraction.line_items?.map((line,index)=>({...line,line_key:`${index}-${line.description}`}));
      setReviewDoc({ id: expense.id, filename: expense.invoice_number || expense.merchant_name || "Expense", status: "editing", created_at: "", extraction });
    } catch (err) {
      setToast(err instanceof Error ? err.message : "Could not load this expense.");
    }
  }
  async function askAssistant(e: FormEvent) {
    e.preventDefault();
    const submittedQuestion = question.trim();
    if (!submittedQuestion || answerBusy) return;
    const history = chatMessages.slice(-4);
    setChatMessages((messages) => [...messages, { role: "user", content: submittedQuestion }]);
    setQuestion("");
    setAnswerBusy(true);
    try {
      const result = await request<{ answer: string; metrics?: Record<string, string> }>("/ai/ask", { method: "POST", body: JSON.stringify({ question: submittedQuestion, history }) });
      setChatMessages((messages) => [...messages, { role: "assistant", content: result.answer }]);
    } catch (err) {
      setChatMessages((messages) => [...messages, {
        role: "assistant",
        content: err instanceof Error ? err.message : "The assistant is unavailable. Please try again.",
      }]);
    }
    finally { setAnswerBusy(false); }
  }
if (!user) return <AuthScreen mode={authMode} setMode={setAuthMode} email={authEmail} setEmail={setAuthEmail} password={authPassword} setPassword={setAuthPassword} name={authName} setName={setAuthName} error={authError} busy={authBusy} onSubmit={submitAuth} />;
  if (user.must_change_password) return <ChangePasswordScreen password={passwordChange} setPassword={setPasswordChange} error={passwordChangeError} busy={passwordChangeBusy} onSubmit={changeTemporaryPassword} />;

  const firstName = user.display_name?.split(" ")[0] || "there";
  const docsAwaiting = documents.filter((d) => d.status === "review").length;
  const currentNav = user.user_role === "admin" ? adminNav : userNav;
  const isOwner = reimbursementWorkspace?.team?.role === "owner";

  return (
    <main className="app-shell">
      <aside className={`sidebar ${mobileNav ? "sidebar-open" : ""}`}>
        <div className="brand">
          <div className="brand-lockup">
            <span className="brand-name">Xpenz<span>IQ</span></span>
            <span className="brand-tagline">Your Expense Expert</span>
          </div>
        </div>
        <div className="nav-group-label">{user.user_role === "admin" ? "ADMIN WORKSPACE" : "EMPLOYEE WORKSPACE"}</div>
        <nav className="nav-list">{currentNav.map((item) => <NavButton key={item.name} item={item} active={view === item.name} badge={item.name === "Documents" ? docsAwaiting : 0} onClick={() => { setView(item.name); setMobileNav(false); }} />)}</nav>
        <div className="sidebar-spacer" />
        <button type="button" className="profile-row" onClick={signOut}><span className="profile-avatar">{(user.display_name || user.email).slice(0,1).toUpperCase()}</span><span className="profile-info"><b>{user.display_name || "Account"}</b><small>{user.email} · {user.user_role === "admin" ? "Administrator" : "Employee"}</small></span><LogOut size={15} /></button>
      </aside>
      {mobileNav && <button type="button" className="mobile-overlay" onClick={() => setMobileNav(false)} aria-label="Close navigation" />}
      <section className="main-column">
        <header className="topbar">
          <button type="button" className="mobile-menu icon-button" onClick={() => setMobileNav(true)} aria-label="Open menu"><Menu size={19} /></button>
          <div className="breadcrumb">Workspace <ChevronRight size={14} /> <b>{view}</b></div>
          <div className="top-actions"><span className="top-date"><CalendarDays size={15} /> {new Intl.DateTimeFormat("en-IN", { weekday: "short", day: "numeric", month: "short" }).format(new Date())}</span>{view === "Dashboard" && <button type="button" className="secondary-button" onClick={exportCsv}><ArrowDownLeft size={14} /> Export CSV</button>}<button type="button" className="icon-button notification" aria-label="Notifications" onClick={() => setToast("You're all caught up.")}><Bell size={17} /><i /></button><span className="top-avatar">{(user.display_name || user.email).slice(0,1).toUpperCase()}</span></div>
        </header>
        <div className="page-content">
          {loadError && <div className="error-banner"><ShieldCheck size={17} /> Can't reach the XpenzIQ API: {loadError} <button type="button" onClick={refreshData}>Retry</button></div>}
          {view === "Dashboard" && <Dashboard firstName={firstName} overview={overview} expenses={expenses} budgets={budgets} documents={documents} onNavigate={setView} onUpload={() => { setUploadStage("drop"); setUploadError(""); setUploadDocumentId(null); setUploadOpen(true); }} onOpenDocument={loadReview} onAnalyzeCategories={analyzeExpenseCategories} categoryAnalysisBusy={categoryAnalysisBusy} />}
          {view === "Documents" && <DocumentsPage docs={documents} onOpenDocument={loadReview} onViewDetails={loadDocumentDetails} detailsLoading={documentDetailsLoading} onDelete={(id) => { setDocuments((list) => list.map((d) => d.id === id ? { ...d, status: "deleted", deleted_at: new Date().toISOString() } : d)); setToast("Document deleted."); request(`/documents/${id}`, { method: "DELETE" }).catch((err) => { setToast(err instanceof Error ? err.message : "Could not delete document."); setDocuments((list) => list.map((d) => d.id === id ? { ...d, status: d.status === "deleted" ? "queued" : d.status } : d)); }); }} />}
          {view === "Expenses" && <ExpensesPage expenses={expenses} currency={overview?.currency || "INR"} onEdit={editExpense} onDelete={async (id) => { try { await request(`/expenses/${id}`, { method: "DELETE" }); await refreshData(); setToast("Expense deleted."); } catch (err) { setToast(err instanceof Error ? err.message : "Could not delete expense."); } }} />}
          {view === "Reimbursements" && isOwner && <ReimbursementsPage workspace={reimbursementWorkspace} expenses={expenses} userId={user.id} categories={categories} onCreateTeam={createReimbursementTeam} onSubmitClaim={submitReimbursementClaim} onDecideClaim={decideReimbursementClaim} onMarkPaid={markReimbursementClaimPaid} onCreateCategory={createCategory} onUpdateCategory={updateCategory} onDeleteCategory={deleteCategory} />}
          {view === "Categories" && user.user_role === "admin" && <CategoriesPage categories={categories} onCreate={createCategory} onUpdate={updateCategory} onDelete={deleteCategory} />}
          {view === "Users" && isOwner && <UsersPage users={reimbursementWorkspace?.members || []} onCreateEmployee={async (payload) => {
            const result = await request<{ user: User; temporary_password: string }>("/reimbursements/users", {
              method: "POST",
              body: JSON.stringify(payload),
            });
            await refreshData();
            setToast(`Employee ${result.user.employee_id} created.`);
            return { employee_id: result.user.employee_id || "", temporary_password: result.temporary_password };
          }} />}
          {view === "Budget" && <BudgetPage budgets={budgets} currency={overview?.currency || "INR"} onAdd={async (payload) => { await request("/budgets", { method: "POST", body: JSON.stringify(payload) }); await refreshData(); setToast("Budget saved."); }} onDelete={async (id) => { await request(`/budgets/${id}`, { method: "DELETE" }); await refreshData(); setToast("Budget deleted."); }} />}
          {view === "MyClaims" && user.user_role === "user" && <MyClaimsPage claims={reimbursementWorkspace?.items || []} />}
          {view === "SubmitClaim" && user.user_role === "user" && <SubmitClaimPage expenses={expenses} categories={categories} onSubmit={submitReimbursementClaim} onCheckLimit={checkClaimLimit} onRequestCategory={requestCategory} />}
          {view === "Settings" && <SettingsPage user={user} />}
          <footer className="footer-note"><span>© 2025 XpenzIQ</span><span>Built for financial clarity <span className="footer-spark">✳</span></span><span>Privacy&nbsp; · &nbsp;Security</span></footer>
        </div>
      </section>
      <div className="stark-chat-dock">
        {chatOpen ? (
          <section className="stark-chat-window" aria-label="Chat with Stark">
            <header className="stark-chat-header">
              <span className="stark-chat-avatar"><Bot size={17} /></span>
              <span className="stark-chat-title"><b>Stark</b><small>Your XpenzIQ assistant</small></span>
              <button type="button" className="stark-window-control" onClick={() => setChatOpen(false)} aria-label="Minimize Stark chat"><Minus size={17} /></button>
              <button type="button" className="stark-window-control" onClick={() => setChatOpen(false)} aria-label="Close Stark chat"><X size={17} /></button>
            </header>
            <div className="stark-chat-messages" aria-live="polite">
              {chatMessages.length === 0 ? (
                <div className="stark-chat-welcome">
                  <span className="stark-welcome-icon"><Sparkles size={18} /></span>
                  <b>Hi{firstName ? `, ${firstName}` : ""}! I’m Stark.</b>
                  <p>Ask me about your expenses, individual invoice items, income, or a spending forecast.</p>
                  <div className="stark-suggestions">
                    {["What is my most expensive purchase?", "How much can I spend through Sunday?"].map((prompt) => (
                      <button type="button" key={prompt} onClick={() => setQuestion(prompt)}>{prompt}</button>
                    ))}
                  </div>
                </div>
              ) : (
                <div className="stark-chat-thread">
                  {chatMessages.map((message, index) => (
                    <div className={`chat-message ${message.role === "user" ? "chat-message-user" : "chat-message-assistant"}`} key={`${index}-${message.role}`}>
                      <span className="chat-message-avatar">{message.role === "user" ? "You" : <Sparkles size={13} />}</span>
                      <div className="chat-message-content">
                        <span className="chat-message-label">{message.role === "user" ? "You" : "Stark"}</span>
                        <p>{message.content}</p>
                      </div>
                    </div>
                  ))}
                  {answerBusy && <div className="stark-typing"><i /><i /><i /> Stark is thinking…</div>}
                  <div ref={chatEndRef} />
                </div>
              )}
            </div>
            <form className="stark-chat-input" onSubmit={askAssistant}>
              <textarea
                value={question}
                onChange={(event) => setQuestion(event.target.value)}
                onKeyDown={(event) => {
                  if (event.key === "Enter" && !event.shiftKey) {
                    event.preventDefault();
                    event.currentTarget.form?.requestSubmit();
                  }
                }}
                placeholder="Write a message…"
                rows={1}
                aria-label="Message Stark"
              />
              <button type="submit" aria-label="Send message" disabled={answerBusy || !question.trim()}><ArrowRight size={18} /></button>
            </form>
          </section>
        ) : (
          <>
            {showStarkPrompt && <div className="stark-launcher-prompt">
              <button type="button" className="stark-prompt-message" onClick={() => setChatOpen(true)}>
                <span className="stark-prompt-avatar"><Bot size={17} /></span>
                <span><b>Stark is here</b><small>Your assistant is ready to help</small></span>
              </button>
              <button type="button" className="stark-prompt-dismiss" onClick={() => setShowStarkPrompt(false)} aria-label="Dismiss Stark greeting"><X size={14} /></button>
            </div>}
            <button type="button" className="stark-chat-launcher" onClick={() => setChatOpen(true)} aria-label="Chat with Stark">
              <Bot size={24} />
              {chatMessages.length > 0 && <span className="stark-launcher-dot" />}
            </button>
          </>
        )}
      </div>
      {uploadOpen && <UploadModal uploadStage={uploadStage} uploadError={uploadError} uploadProgressLabel={uploadProgressLabel} saving={busy} onClose={() => { setUploadOpen(false); setUploadStage("drop"); setUploadError(""); setUploadDocumentId(null); }} onFiles={uploadFiles} onManualExpense={saveManualExpense} />}
      {reviewDoc && <ReviewModal doc={reviewDoc} busy={busy} onClose={() => setReviewDoc(null)} onChange={(extraction) => setReviewDoc({ ...reviewDoc, extraction })} onConfirm={confirmReview} />}
      {documentDetails && <DocumentDetailsModal document={documentDetails.document} details={documentDetails.details} onClose={() => setDocumentDetails(null)} />}
      {toast && <div className="toast"><Check size={16} /><span className="toast-error-message">{renderUploadErrors(toast)}</span><button type="button" onClick={() => setToast("")} aria-label="Dismiss"><X size={14} /></button></div>}
    </main>
  );
}

function NavButton({ item, active, badge, onClick }: { item: { name: View; icon: LucideIcon }; active: boolean; badge?: number; onClick: () => void }) {
  const Icon = item.icon;
  return <button type="button" className={`nav-item ${active ? "active" : ""}`} onClick={onClick}><Icon size={18} strokeWidth={active ? 2.1 : 1.8} /><span>{item.name}</span>{badge ? <em>{badge}</em> : null}</button>;
}

function AuthScreen(props: { mode: "login" | "register"; setMode: (v: "login" | "register") => void; email: string; setEmail: (v: string) => void; password: string; setPassword: (v: string) => void; name: string; setName: (v: string) => void; error: string; busy: boolean; onSubmit: (e: FormEvent) => void }) {
  return <main className="auth-page">
    <section className="auth-panel">
      <div className="auth-card">
        <div className="brand-lockup auth-brand-lockup" aria-label="XpenzIQ, Your Expense Expert">
          <span className="brand-name">Xpenz<span>IQ</span></span>
          <span className="brand-tagline">Your Expense Expert</span>
        </div>
        <h1>{props.mode === "login" ? "Welcome back." : "Make money make sense."}</h1>
        <p className="auth-subtitle">{props.mode === "login" ? "Sign in to pick up where you left off." : "Create your private workspace and get a clearer view of your money."}</p>
        <form onSubmit={props.onSubmit} className="auth-form">
          {props.mode === "register" && <label>Your name<input autoComplete="name" required value={props.name} onChange={(e) => props.setName(e.target.value)} placeholder="Alex Morgan" /></label>}
          <label>{props.mode === "login" ? "Email or employee ID" : "Email address"}<input type={props.mode === "login" ? "text" : "email"} autoComplete={props.mode === "login" ? "username" : "email"} required value={props.email} onChange={(e) => props.setEmail(e.target.value)} placeholder={props.mode === "login" ? "you@example.com or EMP001" : "you@example.com"} /></label>
          <label>Password<input type="password" autoComplete={props.mode === "login" ? "current-password" : "new-password"} minLength={props.mode === "login" ? 1 : 8} required value={props.password} onChange={(e) => props.setPassword(e.target.value)} placeholder={props.mode === "login" ? "Your password" : "At least 8 characters"} /></label>
          {props.error && <div className="inline-error">{props.error}</div>}
          <button type="submit" className="primary-button auth-submit" disabled={props.busy}>{props.busy ? "One moment…" : props.mode === "login" ? "Sign in" : "Create account"}<ArrowRight size={16} /></button>
        </form>
        <div className="auth-secure"><ShieldCheck size={15} /> Your financial data is private and encrypted in transit</div>
      </div>
      <div className="auth-toggle">{props.mode === "login" ? "New to XpenzIQ?" : "Already have an account?"}<button type="button" onClick={() => props.setMode(props.mode === "login" ? "register" : "login")}>{props.mode === "login" ? "Create an account" : "Sign in"}</button></div>
    </section>
  </main>;
}

function ChangePasswordScreen({
  password,
  setPassword,
  error,
  busy,
  onSubmit,
}: {
  password: string;
  setPassword: (value: string) => void;
  error: string;
  busy: boolean;
  onSubmit: (event: FormEvent) => void;
}) {
  return <main className="auth-page">
    <section className="auth-panel">
      <div className="auth-card">
        <div className="brand-lockup auth-brand-lockup">
          <span className="brand-name">Xpenz<span>IQ</span></span>
          <span className="brand-tagline">Your Expense Expert</span>
        </div>
        <h1>Set your password.</h1>
        <p className="auth-subtitle">Your admin gave you a temporary password. Choose a new password before using your account.</p>
        <form onSubmit={onSubmit} className="auth-form">
          <label>New password<input type="password" autoComplete="new-password" minLength={8} maxLength={128} required value={password} onChange={(event) => setPassword(event.target.value)} placeholder="At least 8 characters" /></label>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <button type="submit" className="primary-button auth-submit" disabled={busy}>{busy ? "Updating…" : "Set password"}<ArrowRight size={16} /></button>
        </form>
        <div className="auth-secure"><ShieldCheck size={15} /> Your temporary password will stop working after this change</div>
      </div>
    </section>
  </main>;
}

function PageHeader({ eyebrow, title, description, action }: { eyebrow: string; title: string; description: string; action?: React.ReactNode }) {
  return <div className="page-header"><div><div className="eyebrow">{eyebrow}</div><h1>{title}</h1><p>{description}</p></div>{action}</div>;
}
const categoryColors = ["#10B981", "#3B82F6", "#F59E0B", "#EF4444", "#8B5CF6", "#EC4899", "#06B6D4", "#F97316", "#84CC16", "#6366F1", "#14B8A6", "#64748B"];
function CategoryPie({ data, currency }: { data: Array<{ category: string; total: string; count: number }>; currency: string }) {
  const total = data.reduce((sum, item) => sum + Number(item.total), 0);
  if (!data.length || total <= 0) return <div className="table-empty">No categorized expenses in {currency} yet.</div>;
  let currentAngle = -90;
  const segments = data.map((item, index) => {
    const angle = Number(item.total) / total * 360;
    const startAngle = currentAngle;
    const endAngle = currentAngle + angle;
    currentAngle = endAngle;
    const color = categoryColors[index % categoryColors.length];
    if (data.length === 1) return <circle key={item.category} cx="100" cy="100" r="80" fill={color} />;
    const startX = 100 + 80 * Math.cos((startAngle * Math.PI) / 180);
    const startY = 100 + 80 * Math.sin((startAngle * Math.PI) / 180);
    const endX = 100 + 80 * Math.cos((endAngle * Math.PI) / 180);
    const endY = 100 + 80 * Math.sin((endAngle * Math.PI) / 180);
    return <path key={item.category} d={`M 100 100 L ${startX} ${startY} A 80 80 0 ${angle > 180 ? 1 : 0} 1 ${endX} ${endY} Z`} fill={color} />;
  });
  return (
    <div className="category-pie-wrapper">
      <div className="category-pie">
        <svg viewBox="0 0 200 200" width="200" height="200" role="img" aria-label={`Expense distribution by category in ${currency}`}>
          {segments}
          <circle cx="100" cy="100" r="50" fill="var(--bg)" />
        </svg>
      </div>
      <div className="category-legend">
        {data.map((item, index) => (
          <div key={item.category} className="legend-item">
            <span className="legend-color" style={{ backgroundColor: categoryColors[index % categoryColors.length] }} />
            <span className="legend-label">{item.category}</span>
            <span className="legend-value">{money(item.total, currency)}</span>
            <span className="legend-count">({(Number(item.total) / total * 100).toFixed(0)}%)</span>
          </div>
        ))}
      </div>
    </div>
  );
}
function SpendingLineChart({ data, currency }: { data: Array<{ month: string; total: string }>; currency: string }) {
  const chartWidth = 720;
  const chartHeight = 238;
  const left = 52;
  const right = 12;
  const top = 34;
  const bottom = 42;
  const plotWidth = chartWidth - left - right;
  const plotHeight = chartHeight - top - bottom;
  const maxTotal = Math.max(...data.map((item) => Number(item.total)), 1);
  const points = data.map((item, index) => ({
    ...item,
    x: data.length > 1 ? left + index * plotWidth / (data.length - 1) : left + plotWidth / 2,
    y: top + plotHeight - Number(item.total) / maxTotal * plotHeight,
  }));
  const line = points.reduce((path, point, index) => {
    if (index === 0) return `M ${point.x},${point.y}`;
    const previous = points[index - 1];
    const controlX = (previous.x + point.x) / 2;
    return `${path} C ${controlX},${previous.y} ${controlX},${point.y} ${point.x},${point.y}`;
  }, "");
  const area = points.length
    ? `${line} L ${points[points.length - 1].x},${top + plotHeight} L ${points[0].x},${top + plotHeight} Z`
    : "";
  const hasSpending = data.some((item) => Number(item.total) > 0);
  const yearRange = data.length
    ? Array.from(new Set(data.map((item) => new Date(`${item.month} 1`).getFullYear())))
    : [];
  const yearLabel = yearRange.length === 1
    ? `YEAR: ${yearRange[0]}`
    : yearRange.length > 1
      ? `YEARS: ${yearRange[0]}–${yearRange[yearRange.length - 1]}`
      : "";
  const currencyLabel = (value: number) => new Intl.NumberFormat("en-IN", {
    notation: value >= 100000 ? "compact" : "standard",
    maximumFractionDigits: 1,
  }).format(value);
  const monthLabel = (value: string) => {
    const parsed = new Date(`${value} 1`);
    return Number.isNaN(parsed.getTime())
      ? value
      : new Intl.DateTimeFormat("en", { month: "short" }).format(parsed);
  };

  return (
    <div className="spending-chart">
      <svg viewBox={`0 0 ${chartWidth} ${chartHeight}`} role="img" aria-label={`Monthly expenses by invoice date in ${currency}`} className="spending-line-chart">
        {yearLabel && <text x={chartWidth / 2} y="16" textAnchor="middle" className="spending-year-label">{yearLabel}</text>}
        {[0, 0.5, 1].map((fraction) => {
          const y = top + plotHeight * fraction;
          const value = maxTotal * (1 - fraction);
          return (
            <g key={fraction}>
              <line x1={left} x2={chartWidth - right} y1={y} y2={y} className="spending-gridline" />
              <text x={left - 9} y={y + 4} textAnchor="end" className="spending-axis-label">{currencyLabel(value)}</text>
            </g>
          );
        })}
        {points.length > 1 && <path d={area} className="spending-area" />}
        {points.length > 1 && <path d={line} className="spending-line" />}
        {points.map((point) => (
          <g key={point.month}>
            <circle cx={point.x} cy={point.y} r="5" className="spending-point">
              <title>{`${point.month}: ${money(point.total, currency)}`}</title>
            </circle>
            <text x={point.x} y={chartHeight - 12} textAnchor="middle" className="spending-date-label">{monthLabel(point.month)}</text>
          </g>
        ))}
      </svg>
      {!hasSpending && <p className="spending-empty-note">No recorded expenses for these invoice dates.</p>}
    </div>
  );
}
function Dashboard({ firstName, overview, expenses, budgets, documents, onNavigate, onUpload, onOpenDocument, onAnalyzeCategories, categoryAnalysisBusy }: { firstName: string; overview: Overview | null; expenses: Expense[]; budgets: Budget[]; documents: Document[]; onNavigate: (v: View) => void; onUpload: () => void; onOpenDocument: (d: Document) => void; onAnalyzeCategories: () => void; categoryAnalysisBusy: boolean }) {
  const [categoryCurrency, setCategoryCurrency] = useState(overview?.currency || "INR");
  const [spendingRange, setSpendingRange] = useState("6");
  const [customFromDate, setCustomFromDate] = useState(() => monthInputOffset(5));
  const [customToDate, setCustomToDate] = useState(() => dateInputValue(new Date()));
  const [spendingMonthly, setSpendingMonthly] = useState<Array<{ month: string; total: string }>>([]);
  const [spendingLoading, setSpendingLoading] = useState(true);
  const [spendingError, setSpendingError] = useState("");
  const currency = overview?.currency || "INR";
  const todayDate = dateInputValue(new Date());
  const currentBudget = budgets
    .filter((budget) =>
      budget.currency === currency && budget.start_date <= todayDate && budget.end_date >= todayDate
    )
    .sort((left, right) => {
      const priority = { quarter: 0, half_year: 1, year: 2 };
      return priority[left.period_type] - priority[right.period_type];
    })[0];
  const currentBudgetProgress = currentBudget
    ? Math.min(100, Number(currentBudget.expense_amount) / Number(currentBudget.amount) * 100)
    : 0;
  const currencyTotals = overview?.currency_totals || [];
  const categories = overview?.category_totals || [];
  const availableCategoryCurrencies = [...new Set(categories.map((item) => item.currency))];
  const selectedCategoryCurrency = availableCategoryCurrencies.includes(categoryCurrency)
    ? categoryCurrency
    : availableCategoryCurrencies.includes(currency) ? currency : availableCategoryCurrencies[0] || currency;
  const hour = new Date().getHours();
  const greeting = hour < 12 ? "Good morning" : hour < 18 ? "Good afternoon" : "Good evening";
  const bars = spendingMonthly;
  const recent = expenses.slice(0, 5);
  const today = new Intl.DateTimeFormat("en-IN", { weekday: "long", day: "numeric", month: "long", year: "numeric" }).format(new Date()).toUpperCase();
  useEffect(() => {
    if (spendingRange === "custom" && (!customFromDate || !customToDate || customFromDate > customToDate)) {
      setSpendingMonthly([]);
      setSpendingLoading(false);
      setSpendingError("");
      return;
    }
    let active = true;
    setSpendingLoading(true);
    setSpendingError("");
    const query = spendingRange === "custom"
      ? `from_date=${customFromDate}&to_date=${customToDate}`
      : `months=${spendingRange}`;
    request<{ monthly: Array<{ month: string; total: string }> }>(`/analytics/spending?${query}`)
      .then((result) => { if (active) setSpendingMonthly(result.monthly); })
      .catch((error: unknown) => { if (active) setSpendingError(error instanceof Error ? error.message : "Could not load spending history."); })
      .finally(() => { if (active) setSpendingLoading(false); });
    return () => { active = false; };
  }, [spendingRange, customFromDate, customToDate]);
  return <><PageHeader eyebrow={today} title={`${greeting}, ${firstName}`} description="Here's the shape of your finances today." action={<button type="button" className="primary-button" onClick={onUpload}><Plus size={16} /> Add expense</button>} />
    <div className="metric-grid">
      <Metric title="Current period budget" value={currentBudget ? money(currentBudget.amount, currency) : "Not set"} icon={<Wallet size={17} />} label={currentBudget?.title || "Set a quarter, half-year, or annual budget"} tone="violet" />
      <Metric title="Spent this period" value={currentBudget ? money(currentBudget.expense_amount, currency) : "—"} icon={<ArrowUpRight size={17} />} label={currentBudget ? "Confirmed expenses in this period" : "Create a budget to track spending"} tone="blue" />
      <Metric title="Budget remaining" value={currentBudget ? money(currentBudget.remaining_amount, currency) : "—"} icon={<Activity size={17} />} label={currentBudget ? "Budget less recorded expenses" : "Remaining amount appears here"} tone="green" />
      <Metric title="Needs review" value={String(documents.filter((d) => d.status === "review").length).padStart(2, "0")} icon={<FileCheck2 size={17} />} label="Documents awaiting your review" tone="amber" />
    </div>
    <section className="panel budget-overview-panel">
      <div className="panel-head">
        <div><h2>{currentBudget ? `${currentBudget.title} budget progress` : "Start tracking a budget"}</h2><p>{currentBudget ? `${date(currentBudget.start_date)} – ${date(currentBudget.end_date)}` : "Set a limit and compare it with your confirmed expenses."}</p></div>
        <button type="button" className="text-link" onClick={() => onNavigate("Budget")}>{currentBudget ? "Manage budgets" : "Create a budget"} <ArrowRight size={14} /></button>
      </div>
      {currentBudget ? <div className="budget-progress-track"><div className={currentBudgetProgress >= 100 ? "budget-progress-fill over-budget" : "budget-progress-fill"} style={{ width: `${currentBudgetProgress}%` }} /></div> : null}
      {currentBudget ? <p className="budget-progress-caption">{money(currentBudget.expense_amount, currency)} of {money(currentBudget.amount, currency)} used · {Math.round(currentBudgetProgress)}%</p> : <p className="budget-progress-caption">Budgets can be set for a quarter, half-year, or full year.</p>}
    </section>
    {currencyTotals.length > 1 && (
      <div className="currency-breakdown">
        <h3>Expenses by currency</h3>
        <div className="currency-totals">
          {currencyTotals.map((ct) => (
            <div key={ct.currency} className="currency-total">
              <span>{ct.currency}</span>
              <b>{money(ct.total, ct.currency)}</b>
            </div>
          ))}
        </div>
      </div>
    )}
    <div className="dashboard-grid">
      <section className="panel spending-panel">
        <div className="panel-head">
          <div><h2>Spending overview</h2><p>Monthly totals by invoice date</p></div>
          <div className="spending-filter">
            <select className="select-button" aria-label="Spending overview period" value={spendingRange} onChange={(event) => setSpendingRange(event.target.value)}>
              <option value="1">Last 1 month</option>
              <option value="3">Last 3 months</option>
              <option value="6">Last 6 months</option>
              <option value="custom">Custom range</option>
            </select>
            {spendingRange === "custom" && <>
              <label><span>From</span><input type="date" aria-label="From date" value={customFromDate} max={customToDate || undefined} onChange={(event) => setCustomFromDate(event.target.value)} /></label>
              <label><span>To</span><input type="date" aria-label="To date" value={customToDate} min={customFromDate || undefined} max={dateInputValue(new Date())} onChange={(event) => setCustomToDate(event.target.value)} /></label>
            </>}
          </div>
        </div>
        {spendingLoading ? <div className="chart-empty">Loading spending history…</div>
          : spendingError ? <div className="chart-empty">{spendingError}</div>
          : bars.length ? <SpendingLineChart data={bars} currency={currency} />
          : <div className="chart-empty"><div className="empty-chart-icon"><Activity size={21} /></div><b>No invoice dates in this range</b><span>Enter an invoice date to include the expense in this chart.</span></div>}
      </section>
      <section className="panel category-panel">
        <div className="panel-head">
          <div><h2>Spending by category</h2><p>Expenses grouped by their line-item categories</p></div>
          {availableCategoryCurrencies.length > 1 && <select className="select-button" aria-label="Category chart currency" value={selectedCategoryCurrency} onChange={(event) => setCategoryCurrency(event.target.value)}>{availableCategoryCurrencies.map((item) => <option key={item} value={item}>{item}</option>)}</select>}
        </div>
        <CategoryPie data={categories.filter((item) => item.currency === selectedCategoryCurrency)} currency={selectedCategoryCurrency} />
        {(overview?.uncategorized_count || 0) > 0 && <div className="category-analysis-action"><span>{overview?.uncategorized_count} line item{overview?.uncategorized_count === 1 ? "" : "s"} need categorizing</span><button type="button" className="small-action" onClick={onAnalyzeCategories} disabled={categoryAnalysisBusy}>{categoryAnalysisBusy ? "Analyzing…" : "Analyze with AI"} <Sparkles size={13} /></button></div>}
        {overview?.merchants?.length ? <div className="category-list category-merchants">{overview.merchants.slice(0, 3).map((merchant, index) => <div className="category-row" key={merchant.name}><span className={`category-dot dot-${index % 5}`} /><span>{merchant.name}</span><b>{money(merchant.total, currency)}</b></div>)}</div> : null}
      </section>
    </div>
    <div className="dashboard-grid lower-grid">
      <section className="panel recent-panel"><div className="panel-head"><div><h2>Recent expenses</h2><p>Your latest confirmed records</p></div><button type="button" className="text-link" onClick={() => onNavigate("Expenses")}>View all <ArrowRight size={14} /></button></div>
        {recent.length ? <div className="table-wrap"><table className="data-table"><thead><tr><th>MERCHANT</th><th>DATE</th><th>INVOICE</th><th className="align-right">AMOUNT</th></tr></thead><tbody>{recent.map((e) => <tr key={e.id}><td><span className="merchant-badge">{(e.merchant_name || e.description || "?").slice(0,1).toUpperCase()}</span><b>{e.merchant_name || e.description || "Expense"}</b></td><td>{date(e.expense_date)}</td><td>{e.invoice_number || "—"}</td><td className="align-right amount-cell">{money(e.total_amount, e.currency || currency)}</td></tr>)}</tbody></table></div> : <div className="table-empty"><FileText size={19} /><span>Confirmed expenses will show here.</span></div>}
      </section>
      <section className="panel docs-panel"><div className="panel-head"><div><h2>Documents</h2><p>Recent uploads</p></div><button type="button" className="text-link" onClick={() => onNavigate("Documents")}>View all <ArrowRight size={14} /></button></div>
        {documents.length ? <div className="doc-mini-list">{documents.slice(0,4).map((d) => <button type="button" className="doc-mini" key={d.id} onClick={() => d.status === "review" && onOpenDocument(d)}><span className="pdf-icon"><FileText size={17} /></span><span className="doc-mini-copy"><b>{d.filename}</b><small>{date(d.created_at)}</small></span><StatusPill status={d.status} /></button>)}</div> : <div className="doc-empty"><div><Upload size={19} /></div><b>Nothing uploaded yet</b><span>Upload documents from the Dashboard header.</span></div>}
      </section>
    </div>
  </>;
}
function Metric({ title, value, icon, label, tone }: { title: string; value: string; icon: React.ReactNode; label: string; tone: string }) {
  return <section className="metric-card"><div className={`metric-icon ${tone}`}>{icon}</div><div className="metric-name">{title}</div><div className="metric-value">{value}</div><div className="metric-label">{label}</div></section>;
}
function StatusPill({ status }: { status: string }) {
  const label = status === "review" ? "Review" : status === "completed" ? "Saved" : status === "failed" ? "Failed" : status === "processing" ? "Processing" : status === "queued" ? "Queued" : status === "deleted" ? "Deleted" : status;
  return <span className={`status-pill status-${status}`}>{(status === "processing" || status === "queued") && <i className="status-spinner" />}{label}</span>;
}
function PdfPagePreview({ documentId, filename }: { documentId: string; filename: string }) {
  const [page, setPage] = useState(1);
  const [pageCount, setPageCount] = useState(1);
  const [fitToPage, setFitToPage] = useState(false);
  const [imageUrl, setImageUrl] = useState("");
  const [imageSize, setImageSize] = useState({ width: 1, height: 1 });
  const [error, setError] = useState("");
  const [loading, setLoading] = useState(true);

  useEffect(() => {
    let active = true;
    let objectUrl = "";
    setLoading(true);
    setError("");
    fetch(`${API}/documents/${documentId}/preview/page?page=${page}`, { credentials: "include" })
      .then(async (response) => {
        if (!response.ok) {
          const body = await response.json().catch(() => ({}));
          throw new Error(body.detail || `Could not load PDF page (${response.status}).`);
        }
        return {
          image: await response.blob(),
          pageCount: Number(response.headers.get("X-PDF-Page-Count")) || 1,
          width: Number(response.headers.get("X-PDF-Page-Width")) || 1,
          height: Number(response.headers.get("X-PDF-Page-Height")) || 1,
        };
      })
      .then(({ image, pageCount: count, width, height }) => {
        if (!active) return;
        objectUrl = URL.createObjectURL(image);
        setImageUrl(objectUrl);
        setPageCount(count);
        setImageSize({ width, height });
      })
      .catch((cause: unknown) => {
        if (active) setError(cause instanceof Error ? cause.message : "Could not load this PDF page.");
      })
      .finally(() => {
        if (active) setLoading(false);
      });

    return () => {
      active = false;
      if (objectUrl) URL.revokeObjectURL(objectUrl);
    };
  }, [documentId, page]);

  return (
    <>
      <div className={`pdf-page-canvas ${fitToPage ? "fit-page" : "fit-width"}`}>
        {loading ? <span>Loading PDF page…</span> : error ? <span>{error}</span> : imageUrl ? <Image src={imageUrl} alt={`${filename}, page ${page} of ${pageCount}`} width={imageSize.width} height={imageSize.height} unoptimized /> : null}
      </div>
      <div className="pdf-page-controls">
        <button type="button" className="small-action" onClick={() => setPage((current) => Math.max(1, current - 1))} disabled={page <= 1 || loading} aria-label="Previous PDF page"><ChevronLeft size={14} /> Previous</button>
        <span>Page {page} of {pageCount}</span>
        <button type="button" className="small-action" onClick={() => setFitToPage((current) => !current)} aria-label={fitToPage ? "Fit PDF to width" : "Fit full PDF page"}>{fitToPage ? "Fit width" : "Fit page"}</button>
        <button type="button" className="small-action" onClick={() => setPage((current) => Math.min(pageCount, current + 1))} disabled={page >= pageCount || loading} aria-label="Next PDF page">Next <ChevronRight size={14} /></button>
      </div>
      <a href={`${API}/documents/${documentId}/preview`} target="_blank" rel="noopener noreferrer" className="preview-fallback">
        Open original PDF <ArrowUpRight size={14} />
      </a>
    </>
  );
}
function DocumentsPage({ docs, onOpenDocument, onViewDetails, detailsLoading, onDelete }: { docs: Document[]; onOpenDocument: (d: Document) => void; onViewDetails: (d: Document) => void; detailsLoading: boolean; onDelete: (id: string) => void }) {
  const [search, setSearch] = useState("");
  const filtered = docs.filter((d) =>
    d.filename.toLowerCase().includes(search.toLowerCase()) ||
    (d.stage?.toLowerCase().includes(search.toLowerCase())) ||
    (d.status?.toLowerCase().includes(search.toLowerCase()))
  );
  return (
    <>
      <PageHeader eyebrow="DOCUMENT INTELLIGENCE" title="Your documents" description="Track and review your receipts and invoices." action={null} />
      <div className="toolbar">
        <label className="search-box">
          <Search size={16} />
          <input
            aria-label="Search documents"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search filename, stage, or status"
          />
        </label>
      </div>
      <div className="document-summary">
        <div><span className="summary-dot dot-review" /> Needs review <b>{docs.filter((d) => d.status === "review").length}</b></div>
        <div><span className="summary-dot dot-process" /> Processing <b>{docs.filter((d) => ["queued","processing"].includes(d.status)).length}</b></div>
        <div><span className="summary-dot dot-done" /> Confirmed <b>{docs.filter((d) => d.status === "completed").length}</b></div>
        <div><span className="summary-dot dot-deleted" /> Deleted <b>{docs.filter((d) => d.status === "deleted").length}</b></div>
      </div>
      <section className="panel document-panel"><div className="panel-head"><div><h2>All documents</h2><p>Files are temporarily processed; the original upload is not permanently retained.</p></div></div>
        {filtered.length ? (
          <div className="table-wrap">
            <table className="data-table doc-table">
              <colgroup>
                <col className="doc-column-file" />
                <col className="doc-column-date" />
                <col className="doc-column-stage" />
                <col className="doc-column-status" />
                <col className="doc-column-actions" />
              </colgroup>
              <thead><tr><th>DOCUMENT</th><th>UPLOADED</th><th>PROCESSING STAGE</th><th>STATUS</th><th>ACTIONS</th></tr></thead>
              <tbody>
                {filtered.map((d) => (
                  <tr key={d.id}>
                    <td><span className="pdf-icon"><FileText size={17} /></span><span className="file-name">{d.filename}</span></td>
                    <td>{date(d.created_at)}</td>
                    <td>{d.status === "deleted" ? "Deleted" : (d.stage || (d.status === "review" ? "Ready for your review" : d.status))}</td>
                    <td><StatusPill status={d.status} />{d.error_message && <span className="error-detail">{renderUploadErrors(d.error_message)}</span>}</td>
                    <td className="row-actions">
                      <div className="document-row-actions">
                        {d.status !== "deleted" && (d.status === "review" || d.status === "completed") && <button type="button" className="small-action" onClick={() => onViewDetails(d)} disabled={detailsLoading}><Eye size={13} /> {detailsLoading ? "Loading…" : "View"}</button>}
                        {d.status === "review" && <button type="button" className="small-action" onClick={() => onOpenDocument(d)}>Review <ArrowRight size={13} /></button>}
                        {d.status !== "deleted" && <button type="button" className="small-action document-remove-action" onClick={() => onDelete(d.id)}>Remove</button>}
                        {d.status === "deleted" && <span className="deleted-badge">Deleted</span>}
                      </div>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : <div className="empty-state"><div className="empty-state-icon"><FilePlus2 size={22} /></div><h3>Your document library is ready</h3><p>Upload documents from the Dashboard to get started.</p><small>PDF, JPG, PNG · Up to 20 MB</small></div>}
      </section>
    </>
  );
}
function DocumentDetailsModal({ document, details, onClose }: { document: Document; details: DocumentDetails; onClose: () => void }) {
  const currency = details.currency || "INR";
  const invoiceFields: Array<[string, string | null | undefined]> = [
    ["Merchant", details.seller_name],
    ["Invoice number", details.invoice_number],
    ["Invoice date", details.invoice_date ? date(details.invoice_date) : null],
    ["Document type", details.document_type],
    ["Category", details.category],
    ["Subtotal", details.subtotal ? money(details.subtotal, currency) : null],
    ["Discount", details.discount_total ? money(details.discount_total, currency) : null],
    ["Tax total", [details.cgst, details.sgst, details.igst, details.cess].some(Boolean)
      ? money([details.cgst, details.sgst, details.igst, details.cess].reduce((sum, value) => sum + Number(value || 0), 0), currency)
      : null],
  ];
  return (
    <div className="modal-backdrop" role="presentation" onClick={onClose}>
      <section className="modal document-details-modal" role="dialog" aria-modal="true" aria-labelledby="document-details-title" onClick={(event) => event.stopPropagation()}>
        <button type="button" className="modal-close" onClick={onClose} aria-label="Close document details"><X size={18} /></button>
        <div className="eyebrow">DOCUMENT RECORD</div>
        <h2 id="document-details-title">{document.filename}</h2>
        <p className="document-details-source">{details.expense_saved ? "Saved expense linked to this document" : "Extracted details from this document — not yet saved as an expense"}</p>
        <div className="document-details-total">
          <span>{details.expense_saved ? "Recorded expense total" : "Extracted document total"}</span>
          <b>{details.total ? money(details.total, currency) : "Not available"}</b>
        </div>
        <div className="document-details-fields">
          {invoiceFields.filter(([, value]) => value).map(([label, value]) => (
            <div key={label}><span>{label}</span><b>{value}</b></div>
          ))}
        </div>
        <section className="document-details-lines">
          <h3>Line items <span>{details.line_items?.length || 0}</span></h3>
          {details.line_items?.length ? (
            <div className="table-wrap"><table className="data-table"><thead><tr><th>ITEM</th><th>CATEGORY</th><th>QTY</th><th>UNIT PRICE</th><th className="align-right">LINE TOTAL</th></tr></thead><tbody>
              {details.line_items.map((item, index) => <tr key={item.line_key || `${index}-${item.description}`}><td>{item.description}</td><td>{item.category || details.category || "—"}</td><td>{item.quantity || "—"}{item.unit ? ` ${item.unit}` : ""}</td><td>{item.unit_price ? money(item.unit_price, currency) : "—"}</td><td className="align-right amount-cell">{item.line_total ? money(item.line_total, currency) : "—"}</td></tr>)}
            </tbody></table></div>
          ) : <p className="no-lines">No line items were extracted from this document.</p>}
        </section>
        {details.warnings?.length ? <div className="document-details-warnings"><b>Review notes</b>{details.warnings.map((warning) => <p key={warning}>{warning}</p>)}</div> : null}
        <div className="review-actions"><button type="button" className="primary-button" onClick={onClose}>Close</button></div>
      </section>
    </div>
  );
}
function ExpensesPage({ expenses, currency, onEdit, onDelete }: { expenses: Expense[]; currency: string; onEdit: (expense: Expense) => void; onDelete: (id: string) => Promise<void> }) {
  const [search, setSearch] = useState("");
  const filtered = expenses.filter((e) => `${e.merchant_name || ""} ${e.description || ""} ${e.invoice_number || ""}`.toLowerCase().includes(search.toLowerCase()));

  return (
    <>
      <PageHeader
        eyebrow="SPENDING"
        title="Expenses"
        description="Your confirmed invoice and receipt records."
        action={null}
      />
      <div className="toolbar">
        <label className="search-box">
          <Search size={16} />
          <input
            aria-label="Search merchant or invoice"
            value={search}
            onChange={(e) => setSearch(e.target.value)}
            placeholder="Search merchant or invoice"
          />
        </label>
      </div>
      <section className="panel expense-list">
        <div className="panel-head">
          <div>
            <h2>All expenses</h2>
            <p>
              {filtered.length} confirmed{" "}
              {filtered.length === 1 ? "record" : "records"}
            </p>
          </div>
        </div>
        {filtered.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead>
                <tr>
                  <th>MERCHANT</th>
                  <th>DESCRIPTION</th>
                  <th>DATE</th>
                  <th>INVOICE</th>
                  <th>CATEGORY</th>
                  <th className="align-right">TOTAL</th>
                  <th></th>
                </tr>
              </thead>
              <tbody>
                {filtered.map((e) => (
                  <tr key={e.id}>
                    <td>
                      <span className="merchant-badge">
                        {(e.merchant_name || e.description || "?").slice(0, 1).toUpperCase()}
                      </span>
                      <b>{e.merchant_name || "—"}</b>
                    </td>
                    <td>{e.description || "—"}</td>
                    <td>{date(e.expense_date)}</td>
                    <td>{e.invoice_number || "—"}</td>
                    <td><span className="category-badge">{e.category || "—"}</span></td>
                    <td className="align-right amount-cell">
                      {money(e.total_amount, e.currency || currency)}
                    </td>
                    <td className="row-actions">
                      <button type="button" className="small-action" onClick={() => onEdit(e)}>
                        Edit
                      </button>
                      <button
                        type="button"
                        className="small-action"
                        onClick={() =>
                          window.confirm(`Delete expense from ${e.merchant_name || "this merchant"}?`) &&
                          onDelete(e.id)
                        }
                      >
                        Delete <X size={13} />
                      </button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-empty">
            <CreditCard size={20} />
            <span>
              {search ? "No expenses match your search." : "No confirmed expenses yet."}
            </span>
          </div>
        )}
      </section>
    </>
  );
}
function UsersPage({
  users,
  onCreateEmployee,
}: {
  users: ReimbursementWorkspace["members"];
  onCreateEmployee: (payload: { display_name: string; email: string }) => Promise<{ employee_id: string; temporary_password: string }>;
}) {
  const [displayName, setDisplayName] = useState("");
  const [email, setEmail] = useState("");
  const [credentials, setCredentials] = useState<{ employee_id: string; temporary_password: string } | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const employees = users.filter((member) => member.role === "employee");
  async function submit(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    setCredentials(null);
    try {
      setCredentials(await onCreateEmployee({ display_name: displayName, email }));
      setDisplayName("");
      setEmail("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not add this employee.");
    } finally {
      setSaving(false);
    }
  }
  return <>
    <PageHeader eyebrow="TEAM ADMINISTRATION" title="Users" description="Add employees to your team. Each employee gets an EMP### sign-in ID and can submit reimbursement claims." />
    <section className="panel budget-form">
      <div className="panel-head"><div><h2>Add an employee</h2><p>They sign in with their employee ID and temporary password, then set a private password.</p></div></div>
      <form onSubmit={submit}>
        <div className="budget-form-fields">
          <label>Employee name<input required maxLength={120} value={displayName} onChange={(event) => setDisplayName(event.target.value)} autoComplete="name" /></label>
          <label>Employee email<input required type="email" maxLength={320} value={email} onChange={(event) => setEmail(event.target.value)} autoComplete="email" /></label>
        </div>
        {error && <div className="inline-error" role="alert">{error}</div>}
        <div className="budget-form-actions"><button type="submit" className="primary-button" disabled={saving}>{saving ? "Adding…" : "Add employee"}</button></div>
      </form>
    </section>
    {credentials && <section className="panel budget-form" role="status">
      <div className="panel-head"><div><h2>Employee account created</h2><p>Share these temporary sign-in details privately. The temporary password is the employee ID.</p></div></div>
      <div className="settings-field"><span>Employee ID</span><b>{credentials.employee_id}</b></div>
      <div className="settings-field"><span>Temporary password</span><b>{credentials.temporary_password}</b></div>
      <p>The employee must set a new password after their first sign-in.</p>
    </section>}
    <section className="panel expense-list">
      <div className="panel-head"><div><h2>Employees</h2><p>{employees.length} employee account{employees.length === 1 ? "" : "s"}</p></div></div>
      {employees.length ? <div className="table-wrap"><table className="data-table">
        <thead><tr><th>EMPLOYEE ID</th><th>NAME</th><th>EMAIL</th><th>ACCOUNT STATUS</th></tr></thead>
        <tbody>{employees.map((employee) => <tr key={employee.id}>
          <td><b>{employee.employee_id || "—"}</b></td>
          <td>{employee.display_name || "—"}</td>
          <td>{employee.email}</td>
          <td>{employee.must_change_password ? "Must set password" : "Active"}</td>
        </tr>)}</tbody>
      </table></div> : <div className="table-empty">No employees yet. Add an employee above to create their account.</div>}
    </section>
  </>;
}
function ReimbursementsPage({
  workspace,
  expenses,
  userId,
  categories,
  onCreateTeam,
  onSubmitClaim,
  onDecideClaim,
  onMarkPaid,
  onCreateCategory,
  onUpdateCategory,
  onDeleteCategory,
}: {
  workspace: ReimbursementWorkspace | null;
  expenses: Expense[];
  userId: string;
  categories: ReimbursementCategory[];
  onCreateTeam: (name: string) => Promise<void>;
  onSubmitClaim: (expenseId: string, reason: string) => Promise<void>;
  onDecideClaim: (claimId: string, action: "approve" | "reject", note: string) => Promise<void>;
  onMarkPaid: (claimId: string) => Promise<void>;
  onCreateCategory: (payload: { name: string; description?: string; max_amount: string; currency: string }) => Promise<void>;
  onUpdateCategory: (categoryId: string, payload: { name?: string; description?: string; max_amount?: string; currency?: string; is_active?: boolean }) => Promise<void>;
  onDeleteCategory: (categoryId: string) => Promise<void>;
}) {
  const [teamName, setTeamName] = useState("");
  const [selectedExpenseId, setSelectedExpenseId] = useState("");
  const [reason, setReason] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  if (!workspace) {
    return <><PageHeader eyebrow="EMPLOYEE EXPENSES" title="Reimbursements" description="Loading your team and claims…" /><section className="panel table-empty">Loading reimbursements…</section></>;
  }
  async function createTeam(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onCreateTeam(teamName);
      setTeamName("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not create the team.");
    } finally {
      setSaving(false);
    }
  }
  async function submitClaim(event: FormEvent) {
    event.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onSubmitClaim(selectedExpenseId, reason);
      setSelectedExpenseId("");
      setReason("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit this claim.");
    } finally {
      setSaving(false);
    }
  }
  const claimedExpenseIds = new Set(workspace.items.map((claim) => claim.expense_id).filter((id): id is string => Boolean(id)));
  const availableExpenses = expenses.filter((expense) => !claimedExpenseIds.has(expense.id));
  if (!workspace.team) {
    return <>
      <PageHeader eyebrow="EMPLOYEE EXPENSES" title="Reimbursements" description="Create your admin team, then add employees from the Users tab." />
      <section className="panel budget-form">
        <div className="panel-head"><div><h2>Create an admin team</h2><p>Team owners can add employee accounts and review submitted reimbursement claims.</p></div></div>
        <form onSubmit={createTeam}>
          <div className="budget-form-fields"><label>Team name<input required maxLength={120} value={teamName} onChange={(event) => setTeamName(event.target.value)} placeholder="e.g. Acme Finance" /></label></div>
          <div className="budget-form-actions"><button type="submit" className="primary-button" disabled={saving}>{saving ? "Creating…" : "Create team"}</button></div>
        </form>
      </section>
      {error && <div className="inline-error" role="alert">{error}</div>}
    </>;
  }
  const isOwner = workspace.team.role === "owner";
  const [catShowForm, setCatShowForm] = useState(false);
  const [editingCat, setEditingCat] = useState<ReimbursementCategory | null>(null);
  const [catName, setCatName] = useState("");
  const [catDesc, setCatDesc] = useState("");
  const [catMaxAmount, setCatMaxAmount] = useState("");
  const [catCurrency, setCatCurrency] = useState("INR");
  const [catIsActive, setCatIsActive] = useState(true);
  const [catError, setCatError] = useState("");
  const [catSaving, setCatSaving] = useState(false);

  async function handleCatSubmit(e: FormEvent) {
    e.preventDefault();
    setCatSaving(true);
    setCatError("");
    try {
      if (editingCat) {
        await onUpdateCategory(editingCat.id, { name: catName, description: catDesc, max_amount: catMaxAmount, currency: catCurrency, is_active: catIsActive });
      } else {
        await onCreateCategory({ name: catName, description: catDesc, max_amount: catMaxAmount, currency: catCurrency });
      }
      setCatShowForm(false);
      setEditingCat(null);
      setCatName("");
      setCatDesc("");
      setCatMaxAmount("");
      setCatCurrency("INR");
      setCatIsActive(true);
    } catch (err) {
      setCatError(err instanceof Error ? err.message : "Could not save category.");
    } finally {
      setCatSaving(false);
    }
  }

  function startCatEdit(category: ReimbursementCategory) {
    setEditingCat(category);
    setCatName(category.name);
    setCatDesc(category.description || "");
    setCatMaxAmount(category.max_amount);
    setCatCurrency(category.currency);
    setCatIsActive(category.is_active);
    setCatShowForm(true);
  }

  function startCatCreate() {
    setEditingCat(null);
    setCatName("");
    setCatDesc("");
    setCatMaxAmount("");
    setCatCurrency("INR");
    setCatIsActive(true);
    setCatShowForm(true);
  }

  const activeCategories = categories.filter(c => c.is_active);
  return <>
    <PageHeader
      eyebrow="EMPLOYEE EXPENSES"
      title="Reimbursements"
      description="Submit approved business expenses and track their review and manual payout."
    />
    <section className="panel budget-form">
      <div className="panel-head"><div><h2>{workspace.team.name}</h2><p>{isOwner ? "Team owner · review claims and record manual payments." : "Team member · submit expenses for manager review."} · {workspace.members.length} member{workspace.members.length === 1 ? "" : "s"}</p></div></div>
      <div className="settings-field"><span>Team members</span><b>{workspace.members.map((member) => `${member.employee_id ? `${member.employee_id} · ` : ""}${member.display_name || member.email}`).join(", ")}</b></div>
    </section>
    {isOwner && <section className="panel budget-form">
      <div className="panel-head"><div><h2>Reimbursement Categories</h2><p>Define claim categories with monthly limits. Employees select a category when submitting claims.</p></div></div>
      {catShowForm && (
        <form className="panel budget-form" onSubmit={handleCatSubmit}>
          <div className="panel-head"><div><h2>{editingCat ? "Edit category" : "New reimbursement category"}</h2><p>Set the maximum claimable amount per employee per month.</p></div></div>
          <div className="budget-form-fields">
            <label>Category name<input required maxLength={120} value={catName} onChange={(event) => setCatName(event.target.value)} placeholder="e.g. Travel" /></label>
            <label>Description<textarea maxLength={500} value={catDesc} onChange={(event) => setCatDesc(event.target.value)} placeholder="Optional description" /></label>
            <div className="manual-expense-row">
              <label>Max amount per period<input required type="number" min="0.01" step="0.01" value={catMaxAmount} onChange={(event) => setCatMaxAmount(event.target.value)} placeholder="0.00" /></label>
              <label>Currency<input required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" value={catCurrency} onChange={(event) => setCatCurrency(event.target.value)} /></label>
            </div>
            <label className="checkbox-label">
              <input type="checkbox" checked={catIsActive} onChange={(event) => setCatIsActive(event.target.checked)} />
              <span>Active (employees can select this category)</span>
            </label>
          </div>
          {catError && <div className="inline-error" role="alert">{catError}</div>}
          <div className="budget-form-actions"><button type="button" className="secondary-button" onClick={() => { setCatShowForm(false); setEditingCat(null); }}>Cancel</button><button type="submit" className="primary-button" disabled={catSaving}>{catSaving ? "Saving…" : editingCat ? "Update category" : "Create category"}</button></div>
        </form>
      )}
      {catError && !catShowForm && <div className="inline-error" role="alert">{catError}</div>}
      <section className="panel expense-list">
        <div className="panel-head"><div><h2>All categories</h2><p>{activeCategories.length} categor{activeCategories.length === 1 ? "y" : "ies"} defined</p></div></div>
        {activeCategories.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>NAME</th><th>DESCRIPTION</th><th className="align-right">MAX AMOUNT</th><th>CURRENCY</th><th>STATUS</th><th></th></tr></thead>
              <tbody>
                {activeCategories.map((category) => (
                  <tr key={category.id}>
                    <td><b>{category.name}</b></td>
                    <td>{category.description || "—"}</td>
                    <td className="align-right amount-cell">{money(category.max_amount, category.currency)}</td>
                    <td>{category.currency}</td>
                    <td><span className={`status-pill status-${category.is_active ? "completed" : "failed"}`}>{category.is_active ? "Active" : "Inactive"}</span></td>
                    <td className="row-actions">
                      <button type="button" className="small-action" onClick={() => startCatEdit(category)}>Edit</button>
                      <button type="button" className="small-action" onClick={() => window.confirm(`Delete "${category.name}" category?`) && onDeleteCategory(category.id).catch((err) => setCatError(err instanceof Error ? err.message : "Could not delete category."))}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-empty"><ClipboardList size={20} /><span>No categories yet. Create your first category to enable reimbursement claims.</span></div>
        )}
      </section>
    </section>}
    {!isOwner && <section className="panel budget-form">
      <div className="panel-head"><div><h2>Submit an expense</h2><p>Choose a saved expense record and explain why it is work-related. Each expense can be claimed once.</p></div></div>
      <form onSubmit={submitClaim}>
        <div className="budget-form-fields">
          <label>Expense<select required value={selectedExpenseId} onChange={(event) => setSelectedExpenseId(event.target.value)}>
            <option value="">Choose an expense</option>
            {availableExpenses.map((expense) => <option key={expense.id} value={expense.id}>{expense.merchant_name || expense.description} · {reimbursementMoney(expense.total_amount, expense.currency)} · {date(expense.expense_date)}</option>)}
          </select></label>
          <label>Business purpose<textarea required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain the business purpose for this expense" /></label>
        </div>
        <p>Claims include saved expense details. Original receipt uploads are not retained as reimbursement attachments.</p>
        {!availableExpenses.length && <p>No unclaimed expenses are available. Add and confirm an expense first.</p>}
        <div className="budget-form-actions"><button type="submit" className="primary-button" disabled={saving || !availableExpenses.length}>{saving ? "Submitting…" : "Submit claim"}</button></div>
      </form>
    </section>}
    {error && <div className="inline-error" role="alert">{error}</div>}
    <section className="panel expense-list">
      <div className="panel-head"><div><h2>{isOwner ? "Team claims" : "Your claims"}</h2><p>{workspace.items.length} claim{workspace.items.length === 1 ? "" : "s"} · approved claims must be paid outside XpenzIQ, then marked as paid here</p></div></div>
      {workspace.items.length ? <div className="table-wrap"><table className="data-table">
        <thead><tr>{isOwner && <th>EMPLOYEE</th>}<th>EXPENSE</th><th>DATE</th><th>CATEGORY</th><th>REASON</th><th>STATUS</th><th className="align-right">AMOUNT</th>{isOwner && <th>ACTIONS</th>}</tr></thead>
        <tbody>{workspace.items.map((claim) => <tr key={claim.id}>
          {isOwner && <td><b>{claim.employee_name || claim.employee_email}</b><br /><small>{claim.employee_email}</small></td>}
          <td><b>{claim.merchant_name}</b><br /><small>{claim.description}</small></td>
          <td>{date(claim.expense_date || undefined)}</td>
          <td><span className="category-badge">{claim.category || "—"}</span></td>
          <td>{claim.reason}{claim.review_note && <><br /><small>Review note: {claim.review_note}</small></>}</td>
          <td><span className="category-badge">{claim.status}</span></td>
          <td className="align-right amount-cell">{reimbursementMoney(claim.amount, claim.currency)}</td>
          {isOwner && <td className="row-actions">
            {claim.status === "submitted" && claim.employee_id !== userId && <>
              <button type="button" className="small-action" disabled={saving} onClick={() => onDecideClaim(claim.id, "approve", "").catch((err) => setError(err instanceof Error ? err.message : "Could not approve claim."))}>Approve</button>
              <button type="button" className="small-action" disabled={saving} onClick={() => { const note = window.prompt("Why are you rejecting this claim?"); if (note?.trim()) onDecideClaim(claim.id, "reject", note).catch((err) => setError(err instanceof Error ? err.message : "Could not reject claim.")); }}>Reject</button>
            </>}
            {claim.status === "approved" && <button type="button" className="small-action" disabled={saving} onClick={() => { if (window.confirm("Confirm that this reimbursement was paid outside XpenzIQ?")) onMarkPaid(claim.id).catch((err) => setError(err instanceof Error ? err.message : "Could not update payment status.")); }}>Mark paid</button>}
          </td>}
        </tr>)}</tbody>
      </table></div> : <div className="table-empty">No reimbursement claims yet.</div>}
    </section>
  </>;
}
function BudgetPage({ budgets, currency, onAdd, onDelete }: { budgets: Budget[]; currency: string; onAdd: (payload: { period_type: Budget["period_type"]; period_index: number; year: number; currency: string; amount: string }) => Promise<void>; onDelete: (id: string) => Promise<void> }) {
  const [showForm, setShowForm] = useState(false);
  const [periodType, setPeriodType] = useState<Budget["period_type"]>("quarter");
  const [periodIndex, setPeriodIndex] = useState("1");
  const [year, setYear] = useState(String(new Date().getFullYear()));
  const [budgetAmount, setBudgetAmount] = useState("");
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      await onAdd({
        period_type: periodType,
        period_index: periodType === "year" ? 0 : Number(periodIndex),
        year: Number(year),
        currency,
        amount: budgetAmount,
      });
      setBudgetAmount("");
      setShowForm(false);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save this budget.");
    } finally {
      setSaving(false);
    }
  }
  const sortedBudgets = [...budgets].sort((a, b) => b.start_date.localeCompare(a.start_date));
  return <>
    <PageHeader eyebrow="PLAN YOUR SPENDING" title="Budgets" description="Set a spending limit for each quarter, half-year, or full year, then track confirmed expenses against it." action={<button type="button" className="primary-button" onClick={() => setShowForm((shown) => !shown)}><Plus size={16} /> Add budget</button>} />
    {showForm && <form className="panel budget-form" onSubmit={submit}>
      <div className="panel-head"><div><h2>New spending budget</h2><p>Choose a calendar period and the maximum you plan to spend.</p></div></div>
      <div className="budget-form-fields">
        <label>Budget period<select value={periodType} onChange={(event) => { const selected = event.target.value as Budget["period_type"]; setPeriodType(selected); setPeriodIndex(selected === "year" ? "0" : "1"); }}><option value="quarter">Quarter</option><option value="half_year">Half-year</option><option value="year">Full year</option></select></label>
        {periodType !== "year" && <label>{periodType === "quarter" ? "Quarter" : "Half-year"}<select value={periodIndex} onChange={(event) => setPeriodIndex(event.target.value)}>{(periodType === "quarter" ? [1, 2, 3, 4] : [1, 2]).map((index) => <option key={index} value={index}>{periodType === "quarter" ? `Q${index}` : `H${index}`}</option>)}</select></label>}
        <label>Year<input required type="number" min="2000" max="2100" value={year} onChange={(event) => setYear(event.target.value)} /></label>
        <label>Budget amount ({currency})<input required type="number" min="0.01" step="0.01" value={budgetAmount} onChange={(event) => setBudgetAmount(event.target.value)} placeholder="0.00" /></label>
      </div>
      <div className="budget-form-actions"><button type="button" className="secondary-button" onClick={() => setShowForm(false)}>Cancel</button><button type="submit" className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save budget"}</button></div>
    </form>}
    {error && <div className="inline-error" role="alert">{error}</div>}
    <section className="budget-card-grid">
      {sortedBudgets.map((budget) => {
        const progress = Number(budget.amount) > 0 ? Math.min(100, Number(budget.expense_amount) / Number(budget.amount) * 100) : 0;
        const exceeded = Number(budget.expense_amount) > Number(budget.amount);
        return <article className="panel budget-card" key={budget.id}>
          <div className="budget-card-top"><div><span className="eyebrow">{budget.period_type === "quarter" ? "QUARTERLY" : budget.period_type === "half_year" ? "HALF-YEAR" : "YEARLY"}</span><h2>{budget.title}</h2></div><button type="button" className="small-action" onClick={() => window.confirm(`Delete the ${budget.title} budget?`) && onDelete(budget.id).catch((err) => setError(err instanceof Error ? err.message : "Could not delete budget."))}>Delete <X size={13} /></button></div>
          <p className="budget-card-dates">{date(budget.start_date)} – {date(budget.end_date)}</p>
          <div className="budget-card-amounts"><div><span>Budget</span><b>{money(budget.amount, budget.currency)}</b></div><div><span>Spent</span><b>{money(budget.expense_amount, budget.currency)}</b></div></div>
          <div className="budget-progress-track"><div className={exceeded ? "budget-progress-fill over-budget" : "budget-progress-fill"} style={{ width: `${progress}%` }} /></div>
          <div className="budget-card-footer"><span>{Math.round(progress)}% used</span><b className={exceeded ? "budget-overrun" : ""}>{money(budget.remaining_amount, budget.currency)} left</b></div>
        </article>;
      })}
      {!sortedBudgets.length && <section className="panel budget-empty"><Wallet size={22} /><h2>No budgets yet</h2><p>Create your first budget to compare planned spending with expenses recorded in that period.</p></section>}
    </section>
  </>;
}
function ReportsPage({ overview, onExport }: { overview: Overview | null; onExport: () => void }) {
  const currency = overview?.currency || "INR";
  const currencyTotals = overview?.currency_totals || [];
  const monthly = overview?.monthly || [];
  const categoryTotals = (overview?.category_totals || []).filter((item) => item.currency === currency);
  const monthlyMax = Math.max(...monthly.map((item) => Number(item.total)), 1);

  return (
    <>
      <PageHeader eyebrow="YOUR FINANCES, IN CONTEXT" title="Reports" description="Review confirmed expenses and spending trends." action={<button type="button" className="secondary-button" onClick={onExport}>Export CSV <ArrowDownLeft size={14} /></button>} />
      <div className="metric-grid report-metrics">
        <Metric title="Expenses recorded" value={money(overview?.expenses, currency)} icon={<ArrowUpRight size={17} />} label={`${overview?.expense_count || 0} records`} tone="blue" />
      </div>
      {currencyTotals.length > 1 && (
        <div className="currency-breakdown">
          <h3>Expenses by currency</h3>
          <div className="currency-totals">
            {currencyTotals.map((ct) => (
              <div key={ct.currency} className="currency-total">
                <span>{ct.currency}</span>
                <b>{money(ct.total, ct.currency)}</b>
              </div>
            ))}
          </div>
        </div>
      )}
      {categoryTotals.length > 0 && (
        <section className="panel reports-panel">
          <div className="panel-head">
            <div>
              <h2>Expenses by category</h2>
              <p>Line-item amounts grouped by their assigned categories; older records use invoice totals.</p>
            </div>
          </div>
          <CategoryPie data={categoryTotals} currency={currency} />
        </section>
      )}
      <section className="panel reports-panel"><div className="panel-head"><div><h2>Monthly spending</h2><p>Totals are based on confirmed expense records; unpaid invoices remain expenses, not payments.</p></div></div>{monthly.length ? <div className="report-bars">{monthly.map((item) => <div key={item.month} className="report-bar-row"><span>{item.month}</span><div><i style={{ width: `${Math.min(100, Number(item.total) / monthlyMax * 100)}%` }} /></div><b>{money(item.total, currency)}</b></div>)}</div> : <div className="table-empty">Add and confirm financial records to build your reports.</div>}</section>
    </>
  );
}
function SettingsPage({ user }: { user: User }) {
  return <><PageHeader eyebrow="YOUR ACCOUNT" title="Settings" description="Manage your profile and preferences." /><section className="panel settings-panel"><h2>Profile</h2><p>Your XpenzIQ account details.</p><div className="settings-field"><span>Display name</span><b>{user.display_name || "Not set"}</b></div><div className="settings-field"><span>Email address</span><b>{user.email}</b></div><div className="settings-field"><span>Default currency</span><b>INR · Indian Rupee</b></div><div className="settings-privacy"><ShieldCheck size={18} /><div><b>Your data stays yours</b><p>AI API credentials are kept server-side. Uploaded originals are temporary and are not permanently stored by default.</p></div></div></section></>;
}
function UploadModal({ uploadStage, uploadError, uploadProgressLabel, saving, onClose, onFiles, onManualExpense }: { uploadStage: UploadStage; uploadError: string; uploadProgressLabel: string; saving: boolean; onClose: () => void; onFiles: (files: File[]) => void; onManualExpense: (expense: ManualExpense) => Promise<void> }) {
  const [dragging, setDragging] = useState(false);
  const [progress, setProgress] = useState(0);
  const [mode, setMode] = useState<"invoice" | "manual">("invoice");
  const [merchant, setMerchant] = useState("");
  const [location, setLocation] = useState("");
  const [description, setDescription] = useState("");
  const [expenseDate, setExpenseDate] = useState(dateInputValue(new Date()));
  const [expenseAmount, setExpenseAmount] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [category, setCategory] = useState<ExpenseCategory | "">("");
  const [manualError, setManualError] = useState("");
  const input = useRef<HTMLInputElement>(null);
  useEffect(() => {
    if (["review", "duplicate", "failed"].includes(uploadStage)) {
      setProgress(100);
      return;
    }
    if (!["uploading", "processing"].includes(uploadStage)) {
      setProgress(0);
      return;
    }
    const interval = window.setInterval(() => {
      setProgress((current) => Math.min(current + 10, 90));
    }, 250);
    return () => window.clearInterval(interval);
  }, [uploadStage]);

  function accept(files?: FileList | File[]) {
    if (!files?.length) return;
    setDragging(false);
    const supported = ["application/pdf", "image/jpeg", "image/png", "image/webp"];
    const selected = Array.from(files);
    const valid = selected.filter((file) => supported.includes(file.type) && file.size <= 20 * 1024 * 1024);
    const invalidCount = selected.length - valid.length;
    if (invalidCount) {
      window.alert(`${invalidCount} file${invalidCount === 1 ? " was" : "s were"} skipped. Choose PDF, JPG, PNG, or WebP files up to 20 MB each.`);
    }
    if (valid.length) onFiles(valid);
  }

  async function submitManualExpense(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setManualError("");
    if (!category) {
      setManualError("Choose a category for this expense.");
      return;
    }
    try {
      await onManualExpense({
        merchant,
        location,
        description,
        date: expenseDate,
        amount: expenseAmount,
        currency,
        category,
      });
    } catch (error) {
      setManualError(error instanceof Error ? error.message : "Could not save this expense.");
    }
  }
  
  const stage = uploadStage;
  
  if (stage === "drop") {
    return (
      <div className="modal-backdrop">
        <section className="modal upload-modal">
          <button type="button" className="modal-close" onClick={onClose} aria-label="Close"><X size={18} /></button>
          <div className="modal-icon">{mode === "invoice" ? <Upload size={20} /> : <FilePlus2 size={20} />}</div>
          <div className="eyebrow">ADD AN EXPENSE</div>
          <h2>How would you like to add it?</h2>
          <p>Upload an invoice for AI extraction, or enter the expense details yourself.</p>
          <fieldset className="expense-entry-tabs">
            <legend>Choose an entry method</legend>
            <button type="button" aria-pressed={mode === "invoice"} className={mode === "invoice" ? "active" : ""} onClick={() => setMode("invoice")}><FileText size={15} /> Invoice / receipt</button>
            <button type="button" aria-pressed={mode === "manual"} className={mode === "manual" ? "active" : ""} onClick={() => setMode("manual")}><FilePlus2 size={15} /> Manual entry</button>
          </fieldset>
          {uploadError && <div className="upload-error" role="alert">{renderUploadErrors(uploadError)}</div>}
          {mode === "invoice" ? (
            <>
              <input
                ref={input}
                type="file"
                hidden
                multiple
                accept=".pdf,.png,.jpg,.jpeg,.webp,application/pdf,image/png,image/jpeg,image/webp"
                onChange={(event: ChangeEvent<HTMLInputElement>) => {
                  accept(event.currentTarget.files || undefined);
                  event.currentTarget.value = "";
                }}
              />
              <button
                type="button"
                className={`drop-zone ${dragging ? "dragging" : ""}`}
                onDragOver={(event) => { event.preventDefault(); setDragging(true); }}
                onDragLeave={() => setDragging(false)}
                onDrop={(event) => { event.preventDefault(); accept(event.dataTransfer.files); }}
                onClick={() => input.current?.click()}
              >
                <span className="drop-cloud"><Upload size={20} /></span>
                <b>Drop your invoice or receipt here</b>
                <span>or <u>browse files</u> on your device</span>
                <small>PDF, JPG, PNG, WebP · up to 20 MB per file</small>
              </button>
              <div className="upload-privacy"><ShieldCheck size={15} /> Original files are processed temporarily, then removed.</div>
            </>
          ) : (
            <form className="manual-expense-form" onSubmit={submitManualExpense}>
              <label>Merchant or place<input required maxLength={255} value={merchant} onChange={(event) => setMerchant(event.target.value)} placeholder="Where did you spend?" /></label>
              <label>Location (optional)<input maxLength={120} value={location} onChange={(event) => setLocation(event.target.value)} placeholder="City, shop, or address" /></label>
              <label>Description<input required maxLength={1000} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="What was the expense for?" /></label>
              <div className="manual-expense-row">
                <label>Amount<input required type="number" min="0.01" step="0.01" value={expenseAmount} onChange={(event) => setExpenseAmount(event.target.value)} placeholder="0.00" /></label>
                <label>Currency<input required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" value={currency} onChange={(event) => setCurrency(event.target.value)} /></label>
              </div>
              <div className="manual-expense-row">
                <label>Date<input required type="date" value={expenseDate} onChange={(event) => setExpenseDate(event.target.value)} /></label>
                <label>Category<select required value={category} onChange={(event) => setCategory(event.target.value as ExpenseCategory | "")}>
                  <option value="">Choose category</option>
                  {expenseCategories.map((item) => <option key={item} value={item}>{item}</option>)}
                </select></label>
              </div>
              {manualError && <div className="upload-error" role="alert">{manualError}</div>}
              <div className="manual-expense-actions">
                <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
                <button type="submit" className="primary-button" disabled={saving}>{saving ? "Saving…" : "Save expense"}</button>
              </div>
            </form>
          )}
        </section>
      </div>
    );
  }
  const terminalStage = ["review", "duplicate", "failed"].includes(stage);
  const title = stage === "review" ? "Ready for review"
    : stage === "duplicate" ? "Duplicate invoice detected"
      : stage === "failed" ? "Could not process document"
        : "Processing document";
  const statusMessage = stage === "review" ? "Invoice details are ready. Open Documents to review and save them."
    : stage === "duplicate" ? "This upload matches an existing expense, so it was not added again."
      : stage === "failed" ? "The document could not be processed. Check its status in Documents."
        : stage === "uploading" ? "Uploading file…"
          : "Reading the document and checking for duplicates…";
  return <div className="modal-backdrop"><section className="modal upload-modal"><div className="modal-icon">{stage === "duplicate" ? <CircleHelp size={20} /> : <FileCheck2 size={20} />}</div><div className="eyebrow">{terminalStage ? "PROCESSING RESULT" : "DOCUMENT UPLOAD"}</div><h2>{title}</h2><div className="upload-progress"><div className="progress-bar" role="progressbar" aria-valuenow={progress} aria-valuemin={0} aria-valuemax={100}><div className="progress-fill" style={{ width: `${progress}%` }} /></div><span className="progress-text">{stage === "uploading" || stage === "processing" ? uploadProgressLabel || statusMessage : statusMessage}</span></div>{uploadError && <div className="upload-error" role="alert">{renderUploadErrors(uploadError)}</div>}<div className="upload-stages"><div className={`stage ${["processing", "review", "duplicate", "failed"].includes(stage) ? "done" : ""}`}><span className="stage-dot" /><span>Upload</span></div><div className={`stage ${["review", "duplicate", "failed"].includes(stage) ? "done" : ""}`}><span className="stage-dot" /><span>Queue</span></div><div className={`stage ${terminalStage ? "done" : ""}`}><span className="stage-dot" /><span>Processing</span></div></div><div className="upload-privacy"><ShieldCheck size={15} /> Original files are processed temporarily, then removed.</div><button type="button" className="primary-button full-button" onClick={onClose}>{terminalStage ? "Close" : "Close and continue in background"}</button></section></div>;
}
function ReviewModal({ doc, busy, onClose, onChange, onConfirm }: { doc: Document; busy: boolean; onClose: () => void; onChange: (data: Invoice) => void; onConfirm: () => void }) {
  const data = doc.extraction || {};
  const previewUrl = (doc as Document & { previewUrl?: string }).previewUrl;
  const isPdf = doc.filename?.toLowerCase().endsWith(".pdf");
  const update = (key: keyof Invoice, value: string) => onChange({ ...data, [key]: value || null });
  const updateLine = (index: number, key: keyof InvoiceLine, value: string) => {
    const lines = [...(data.line_items || [])];
    lines[index] = { ...lines[index], [key]: key === "description" || key === "unit" || key === "hsn_sac_code" ? value : value || null };
    onChange({ ...data, line_items: lines });
  };
  const fields: Array<[keyof Invoice, string, "text" | "date" | "number"]> = [
    ["document_type","Document type","text"],["invoice_number","Invoice number","text"],
    ["invoice_date","Invoice date","date"],["due_date","Due date","date"],
    ["currency","Currency","text"],["seller_name","Seller name","text"],
    ["buyer_name","Buyer name","text"],["seller_gstin","Seller GSTIN","text"],
    ["buyer_gstin","Buyer GSTIN","text"],["billing_address","Billing address","text"],
    ["shipping_address","Shipping address","text"],["place_of_supply","Place of supply","text"],
    ["payment_terms","Payment terms","text"],["subtotal","Subtotal","number"],
    ["discount_total","Total discounts","number"],["taxable_value","Taxable value","number"],
    ["cgst","CGST","number"],["sgst","SGST","number"],["igst","IGST","number"],
    ["cess","Cess","number"],["other_charges","Other charges","number"],
    ["round_off","Round-off","number"],["total","Invoice total","number"],
  ];
  const lineFields = [
    ["description","Description","text"],
    ["hsn_sac_code","HSN / SAC","text"],
    ["quantity","Quantity","number"],
    ["unit","Unit","text"],
    ["unit_price","Unit price","number"],
    ["discount","Discount","number"],
    ["taxable_amount","Taxable amount","number"],
    ["gst_rate","GST %","number"],
  ] as const;

  return (
    <div className="modal-backdrop">
      <section className="modal review-modal review-modal-split">
        <button type="button" className="modal-close" onClick={onClose} aria-label="Close review"><X size={18} /></button>
        <div className="eyebrow">CHECK BEFORE SAVING</div>
        <h2>Review extracted details</h2>
        <p className="review-filename"><FileText size={15} /> {doc.filename} <StatusPill status="review" /></p>
        <div className="review-split">
          <div className="review-original">
            <h3>Original Document</h3>
            <div className="document-preview">
              {previewUrl ? (
                isPdf ? (
                  <PdfPagePreview documentId={doc.id} filename={doc.filename} />
                ) : (
                  <img src={previewUrl} alt={doc.filename} />
                )
              ) : isPdf ? (
                <PdfPagePreview documentId={doc.id} filename={doc.filename} />
              ) : (
                <div className="preview-placeholder">
                  <FileText size={32} />
                  <p>Original document not available</p>
                  <small>Preview endpoint may not be implemented</small>
                  <a href={`${API}/documents/${doc.id}/preview`} target="_blank" rel="noopener noreferrer" className="preview-fallback" style={{ marginTop: 8, display: "inline-block" }}>
                    Try opening directly <ArrowUpRight size={14} />
                  </a>
                </div>
              )}
            </div>
            {previewUrl && !isPdf && <p className="preview-debug" style={{fontSize:10,color:"var(--green)",marginTop:8}}><Check size={10} /> Preview loaded from blob URL</p>}
          </div>
          <div className="review-parsed">
            <div className="review-fields">
              {fields.map(([key, label, type]) => (
                <label key={key}>
                  {label}
                  <input
                    type={type}
                    step={type === "number" ? "0.01" : undefined}
                    value={(data[key] as string) || ""}
                    onChange={(e) => update(key, e.target.value)}
                    placeholder="Not found — add if known"
                  />
                </label>
              ))}
            </div>
            <div className="review-lines">
              <div className="review-lines-heading">
                <h3>Line items <span>{data.line_items?.length || 0}</span></h3>
                <button
                  type="button"
                  className="small-action"
                  onClick={() => onChange({ ...data, line_items: [...(data.line_items || []), { line_key: `new-${crypto.randomUUID()}`, description: "", category: null }] })}
                >
                  <Plus size={13} /> Add line
                </button>
              </div>
              {data.line_items?.length ? (
                <div className="review-item-list">
                  {data.line_items.map((line, index) => (
                    <div className="review-item-card" key={line.line_key || `${index}-${line.description}`}>
                      <div className="review-item-title">
                        <b>Item {index + 1}</b>
                        <label className="line-category-field">
                          AI-suggested category
                          <select
                            aria-label={`Category for item ${index + 1}`}
                            title="Review the AI suggestion and change it only if needed."
                            value={line.category || ""}
                            onChange={(event) => updateLine(index, "category", event.target.value)}
                          >
                            <option value="">Select category</option>
                            {expenseCategories.map((category) => <option key={category} value={category}>{category}</option>)}
                          </select>
                        </label>
                        <button
                          type="button"
                          className="small-action remove-line"
                          onClick={() => onChange({ ...data, line_items: data.line_items?.filter((_, lineIndex) => lineIndex !== index) })}
                        >
                          <X size={13} /> Remove
                        </button>
                      </div>
                      <div className="review-item-fields">
                        {lineFields.map(([lkey, llabel, ltype]) => (
                          <label key={lkey} htmlFor={`invoice-line-${index}-${lkey}`}>
                            {llabel}
                            <input
                              id={`invoice-line-${index}-${lkey}`}
                              type={ltype}
                              step={ltype === "number" ? "0.01" : undefined}
                              value={(line[lkey as keyof InvoiceLine] as string) || ""}
                              onChange={(e) => updateLine(index, lkey as keyof InvoiceLine, e.target.value)}
                              placeholder="—"
                            />
                          </label>
                        ))}
                      </div>
                    </div>
                  ))}
                </div>
              ) : (
                <p className="no-lines">No line items extracted</p>
              )}
            </div>
            <div className="review-actions">
              <button type="button" className="secondary-button" onClick={onClose}>Cancel</button>
              <button type="button" className="primary-button" onClick={onConfirm} disabled={busy}>
                {busy ? "Saving…" : "Confirm & Save"}
              </button>
            </div>
          </div>
</div>
      </section>
    </div>
  );
}

function CategoriesPage({ categories, onCreate, onUpdate, onDelete }: { categories: ReimbursementCategory[]; onCreate: (payload: { name: string; description?: string; max_amount: string; currency: string }) => Promise<void>; onUpdate: (categoryId: string, payload: { name?: string; description?: string; max_amount?: string; currency?: string; is_active?: boolean }) => Promise<void>; onDelete: (categoryId: string) => Promise<void> }) {
  const [showForm, setShowForm] = useState(false);
  const [editingCategory, setEditingCategory] = useState<ReimbursementCategory | null>(null);
  const [name, setName] = useState("");
  const [description, setDescription] = useState("");
  const [maxAmount, setMaxAmount] = useState("");
  const [currency, setCurrency] = useState("INR");
  const [isActive, setIsActive] = useState(true);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);

  async function handleSubmit(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (editingCategory) {
        await onUpdate(editingCategory.id, { name, description, max_amount: maxAmount, currency, is_active: isActive });
      } else {
        await onCreate({ name, description, max_amount: maxAmount, currency });
      }
      setShowForm(false);
      setEditingCategory(null);
      setName("");
      setDescription("");
      setMaxAmount("");
      setCurrency("INR");
      setIsActive(true);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not save category.");
    } finally {
      setSaving(false);
    }
  }

  function startEdit(category: ReimbursementCategory) {
    setEditingCategory(category);
    setName(category.name);
    setDescription(category.description || "");
    setMaxAmount(category.max_amount);
    setCurrency(category.currency);
    setIsActive(category.is_active);
    setShowForm(true);
  }

  function startCreate() {
    setEditingCategory(null);
    setName("");
    setDescription("");
    setMaxAmount("");
    setCurrency("INR");
    setIsActive(true);
    setShowForm(true);
  }

  return (
    <>
      <PageHeader eyebrow="REIMBURSEMENT SETTINGS" title="Categories" description="Define reimbursement categories with claim limits. Employees can only claim up to the maximum amount per period." action={<button type="button" className="primary-button" onClick={startCreate}><Plus size={16} /> Add category</button>} />
      {showForm && (
        <form className="panel budget-form" onSubmit={handleSubmit}>
          <div className="panel-head"><div><h2>{editingCategory ? "Edit category" : "New reimbursement category"}</h2><p>Set the maximum claimable amount per employee per month.</p></div></div>
          <div className="budget-form-fields">
            <label>Category name<input required maxLength={120} value={name} onChange={(event) => setName(event.target.value)} placeholder="e.g. Travel" /></label>
            <label>Description<textarea maxLength={500} value={description} onChange={(event) => setDescription(event.target.value)} placeholder="Optional description" /></label>
            <div className="manual-expense-row">
              <label>Max amount per period<input required type="number" min="0.01" step="0.01" value={maxAmount} onChange={(event) => setMaxAmount(event.target.value)} placeholder="0.00" /></label>
              <label>Currency<input required minLength={3} maxLength={3} pattern="[A-Za-z]{3}" value={currency} onChange={(event) => setCurrency(event.target.value)} /></label>
            </div>
            <label className="checkbox-label">
              <input type="checkbox" checked={isActive} onChange={(event) => setIsActive(event.target.checked)} />
              <span>Active (employees can select this category)</span>
            </label>
          </div>
          {error && <div className="inline-error" role="alert">{error}</div>}
          <div className="budget-form-actions"><button type="button" className="secondary-button" onClick={() => { setShowForm(false); setEditingCategory(null); }}>Cancel</button><button type="submit" className="primary-button" disabled={saving}>{saving ? "Saving…" : editingCategory ? "Update category" : "Create category"}</button></div>
        </form>
      )}
      {error && !showForm && <div className="inline-error" role="alert">{error}</div>}
      <section className="panel expense-list">
        <div className="panel-head"><div><h2>All categories</h2><p>{categories.length} categor{categories.length === 1 ? "y" : "ies"} defined</p></div></div>
        {categories.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>NAME</th><th>DESCRIPTION</th><th className="align-right">MAX AMOUNT</th><th>CURRENCY</th><th>STATUS</th><th></th></tr></thead>
              <tbody>
                {categories.map((category) => (
                  <tr key={category.id}>
                    <td><b>{category.name}</b></td>
                    <td>{category.description || "—"}</td>
                    <td className="align-right amount-cell">{money(category.max_amount, category.currency)}</td>
                    <td>{category.currency}</td>
                    <td><span className={`status-pill status-${category.is_active ? "completed" : "failed"}`}>{category.is_active ? "Active" : "Inactive"}</span></td>
                    <td className="row-actions">
                      <button type="button" className="small-action" onClick={() => startEdit(category)}>Edit</button>
                      <button type="button" className="small-action" onClick={() => window.confirm(`Delete "${category.name}" category?`) && onDelete(category.id).catch((err) => setError(err instanceof Error ? err.message : "Could not delete category."))}>Delete</button>
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-empty"><ClipboardList size={20} /><span>No categories yet. Create your first category to enable reimbursement claims.</span></div>
        )}
      </section>
    </>
  );
}

function MyClaimsPage({ claims }: { claims: ReimbursementClaim[] }) {
  return (
    <>
      <PageHeader eyebrow="MY CLAIMS" title="My Reimbursement Claims" description="Track the status of your submitted reimbursement claims." action={null} />
      <section className="panel expense-list">
        <div className="panel-head"><div><h2>Your claims</h2><p>{claims.length} claim{claims.length === 1 ? "" : "s"} submitted</p></div></div>
        {claims.length ? (
          <div className="table-wrap">
            <table className="data-table">
              <thead><tr><th>EXPENSE</th><th>DATE</th><th>CATEGORY</th><th>REASON</th><th>STATUS</th><th className="align-right">AMOUNT</th></tr></thead>
              <tbody>
                {claims.map((claim) => (
                  <tr key={claim.id}>
                    <td><b>{claim.merchant_name}</b><br /><small>{claim.description}</small></td>
                    <td>{date(claim.expense_date || undefined)}</td>
                    <td><span className="category-badge">{claim.category || "—"}</span></td>
                    <td>{claim.reason}</td>
                    <td><span className="category-badge">{claim.status}</span></td>
                    <td className="align-right amount-cell">{reimbursementMoney(claim.amount, claim.currency)}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <div className="table-empty"><ClipboardList size={20} /><span>No claims submitted yet. Use "Submit Claim" to create a new reimbursement request.</span></div>
        )}
      </section>
    </>
  );
}

function SubmitClaimPage({ expenses, categories, onSubmit, onCheckLimit, onRequestCategory }: { expenses: Expense[]; categories: ReimbursementCategory[]; onSubmit: (expenseId: string, reason: string, categoryId?: string, claimAmount?: string, receiptFile?: File) => Promise<void>; onCheckLimit: (expenseId: string, categoryId: string, claimAmount?: string) => Promise<ClaimLimitCheck>; onRequestCategory: (name: string, description: string) => Promise<void>; }) {
  const [selectedCategoryId, setSelectedCategoryId] = useState("");
  const [reason, setReason] = useState("");
  const [purchaseAmount, setPurchaseAmount] = useState("");
  const [claimAmount, setClaimAmount] = useState("");
  const [receiptFile, setReceiptFile] = useState<File | null>(null);
  const [error, setError] = useState("");
  const [saving, setSaving] = useState(false);
  const [limitCheck, setLimitCheck] = useState<ClaimLimitCheck | null>(null);
  const [checkingLimit, setCheckingLimit] = useState(false);
  const [showCategoryRequest, setShowCategoryRequest] = useState(false);
  const [requestCategoryName, setRequestCategoryName] = useState("");
  const [requestCategoryDesc, setRequestCategoryDesc] = useState("");
  const [requestingCategory, setRequestingCategory] = useState(false);

  const activeCategories = categories.filter((c) => c.is_active);
  const selectedCategory = activeCategories.find(c => c.id === selectedCategoryId);
  const categoryHasLimit = selectedCategory && Number(selectedCategory.max_amount) > 0;

  async function handleCategorySelect(categoryId: string) {
    setSelectedCategoryId(categoryId);
    setLimitCheck(null);
    setClaimAmount("");
    setPurchaseAmount("");
  }

  async function handlePurchaseAmountChange(e: React.ChangeEvent<HTMLInputElement>) {
    setPurchaseAmount(e.target.value);
    if (selectedCategoryId && categoryHasLimit) {
      setCheckingLimit(true);
      try {
        const result = await onCheckLimit("", selectedCategoryId, e.target.value);
        setLimitCheck(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not check claim limit.");
      } finally {
        setCheckingLimit(false);
      }
    }
  }

  async function handleClaimAmountChange(e: React.ChangeEvent<HTMLInputElement>) {
    const value = e.target.value;
    if (categoryHasLimit && selectedCategory) {
      const maxAllowed = Number(selectedCategory.max_amount);
      if (Number(value) > maxAllowed) {
        setClaimAmount(maxAllowed.toFixed(2));
        return;
      }
    }
    setClaimAmount(value);
    if (selectedCategoryId) {
      setCheckingLimit(true);
      try {
        const result = await onCheckLimit("", selectedCategoryId, value);
        setLimitCheck(result);
      } catch (err) {
        setError(err instanceof Error ? err.message : "Could not check claim limit.");
      } finally {
        setCheckingLimit(false);
      }
    }
  }

  async function submitClaim(e: FormEvent) {
    e.preventDefault();
    setSaving(true);
    setError("");
    try {
      if (limitCheck && !limitCheck.can_claim) {
        setError(limitCheck.message || "Claim exceeds category limit.");
        return;
      }
      const amountToClaim = claimAmount || purchaseAmount || "0";
      await onSubmit(selectedCategoryId, reason, selectedCategoryId, amountToClaim, receiptFile || undefined);
      setSelectedCategoryId("");
      setReason("");
      setPurchaseAmount("");
      setClaimAmount("");
      setReceiptFile(null);
      setLimitCheck(null);
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not submit claim.");
    } finally {
      setSaving(false);
    }
  }

  async function requestNewCategory(e: FormEvent) {
    e.preventDefault();
    setRequestingCategory(true);
    setError("");
    try {
      await onRequestCategory(requestCategoryName, requestCategoryDesc);
      setShowCategoryRequest(false);
      setRequestCategoryName("");
      setRequestCategoryDesc("");
    } catch (err) {
      setError(err instanceof Error ? err.message : "Could not request category.");
    } finally {
      setRequestingCategory(false);
    }
  }

  function handleFileChange(e: React.ChangeEvent<HTMLInputElement>) {
    const file = e.target.files?.[0];
    if (file) {
      const allowedTypes = ["application/pdf", "image/png", "image/jpeg", "image/webp"];
      if (!allowedTypes.includes(file.type)) {
        setError("Only PDF, PNG, JPG, or WebP files are allowed.");
        return;
      }
      if (file.size > 20 * 1024 * 1024) {
        setError("File must be 20 MB or smaller.");
        return;
      }
      setReceiptFile(file);
      setError("");
    }
  }

  if (!activeCategories.length) {
    return (
      <>
        <PageHeader eyebrow="SUBMIT CLAIM" title="Submit Reimbursement Claim" description="No reimbursement categories are available. Request a new category from your admin." action={null} />
        <section className="panel budget-form">
          <div className="panel-head"><div><h2>No categories available</h2><p>Your admin hasn't set up any reimbursement categories yet. You can request a new category below.</p></div></div>
          <form onSubmit={requestNewCategory} className="budget-form-fields">
            <label>Category name<input required maxLength={120} value={requestCategoryName} onChange={(e) => setRequestCategoryName(e.target.value)} placeholder="e.g. Travel, Meals, Training" /></label>
            <label>Description<textarea maxLength={500} value={requestCategoryDesc} onChange={(e) => setRequestCategoryDesc(e.target.value)} placeholder="Explain what this category should cover" /></label>
            {error && <div className="inline-error" role="alert">{error}</div>}
            <div className="budget-form-actions"><button type="button" className="secondary-button" onClick={() => setShowCategoryRequest(false)}>Cancel</button><button type="submit" className="primary-button" disabled={requestingCategory || !requestCategoryName.trim()}>{requestingCategory ? "Requesting…" : "Request Category"}</button></div>
          </form>
        </section>
      </>
    );
  }

  return (
    <>
      <PageHeader eyebrow="SUBMIT CLAIM" title="Submit Reimbursement Claim" description="Select a reimbursement category, upload your receipt, and enter the amount you're claiming." action={null} />
      
      <section className="panel budget-form">
        <div className="panel-head"><div><h2>Available Reimbursement Categories</h2><p>Choose a category to see its details and submit a claim.</p></div></div>
        
        <div className="category-grid">
          {activeCategories.map((cat) => (
            <article key={cat.id} className={`category-card ${selectedCategoryId === cat.id ? "selected" : ""}`} onClick={() => handleCategorySelect(cat.id)}>
              <div className="category-card-header">
                <h3>{cat.name}</h3>
                <span className="category-max-amount">{money(cat.max_amount, cat.currency)}</span>
              </div>
              {cat.description && <p className="category-description">{cat.description}</p>}
              <div className="category-meta">
                <span className="category-period">Monthly limit</span>
                {cat.max_amount === "0" || cat.max_amount === "0.00" ? <span className="category-unlimited">No limit</span> : <span className="category-limit">{money(cat.max_amount, cat.currency)} per month</span>}
              </div>
              {selectedCategoryId === cat.id && <div className="category-selected-indicator">Selected</div>}
            </article>
          ))}
        </div>

        {selectedCategory && (
          <>
            <div className="selected-category-banner">
              <div className="selected-category-info">
                <h3>{selectedCategory.name}</h3>
                <p>{selectedCategory.description || "No description provided."}</p>
                <div className="selected-category-limits">
                  <span>Monthly limit: <strong>{money(selectedCategory.max_amount, selectedCategory.currency)}</strong></span>
                  {categoryHasLimit ? <span>You can claim up to <strong>{money(selectedCategory.max_amount, selectedCategory.currency)}</strong></span> : <span className="unlimited-badge">No limit set</span>}
                </div>
              </div>
              <button type="button" className="secondary-button" onClick={() => { setSelectedCategoryId(""); setClaimAmount(""); setPurchaseAmount(""); setLimitCheck(null); }}>Change Category</button>
            </div>

            <form onSubmit={submitClaim}>
              <div className="budget-form-fields">
                <label>Upload Receipt <span className="required">*</span>
                  <input type="file" accept=".pdf,.png,.jpg,.jpeg,.webp" onChange={handleFileChange} required />
                </label>
              </div>
              
              <div className="budget-form-fields">
                <label>Purchase Amount <span className="required">*</span>
                  <input type="number" min="0.01" step="0.01" value={purchaseAmount} onChange={handlePurchaseAmountChange} placeholder="Enter the actual purchase amount" required />
                </label>
              </div>

              <div className="budget-form-fields">
                <label>Claim Amount <span className="required">*</span>
                  <input type="number" min="0.01" step="0.01" value={claimAmount} onChange={handleClaimAmountChange} placeholder={categoryHasLimit ? `Max: ${money(Number(selectedCategory?.max_amount || 0), selectedCategory?.currency)}` : "Enter claim amount"} required />
                </label>
              </div>

              <div className="budget-form-fields">
                <label>Business Purpose <span className="required">*</span>
                  <textarea required maxLength={2000} value={reason} onChange={(event) => setReason(event.target.value)} placeholder="Explain the business purpose for this expense" />
                </label>
              </div>

              {limitCheck && (
                <div className={`limit-check ${limitCheck.can_claim ? "limit-ok" : "limit-exceeded"}`}>
                  <div className="limit-check-header">
                    <span className="limit-check-category">{limitCheck.category_name}</span>
                    <span className={`limit-check-status ${limitCheck.can_claim ? "ok" : "exceeded"}`}>
                      {limitCheck.can_claim ? "Within limit" : "Limit exceeded"}
                    </span>
                  </div>
                  <div className="limit-check-details">
                    <div><span>Period limit</span><b>{money(limitCheck.max_amount, limitCheck.currency)}</b></div>
                    <div><span>Claimed this period</span><b>{money(limitCheck.claimed_this_period, limitCheck.currency)}</b></div>
                    <div><span>Remaining</span><b>{money(limitCheck.remaining_amount, limitCheck.currency)}</b></div>
                    <div><span>This claim</span><b>{money(claimAmount || purchaseAmount || "0", limitCheck.currency)}</b></div>
                  </div>
                  {limitCheck.message && <p className="limit-check-message">{limitCheck.message}</p>}
                </div>
              )}

              {receiptFile && <p className="file-preview">Receipt attached: {receiptFile.name} ({(receiptFile.size / 1024).toFixed(1)} KB)</p>}
              {error && <div className="inline-error" role="alert">{error}</div>}
              
              <div className="budget-form-actions">
                <button type="submit" className="primary-button" disabled={saving || !receiptFile || !purchaseAmount || !claimAmount || !reason.trim() || (limitCheck !== null && !limitCheck.can_claim)}>
                  {saving ? "Submitting…" : "Submit Claim for Approval"}
                </button>
              </div>
            </form>
          </>
        )}
      </section>
    </>
  );
}
