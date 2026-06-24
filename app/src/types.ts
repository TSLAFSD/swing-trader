export type Market = "us" | "kr";

export interface SignalCard {
  signal_date: string | null;
  ticker: string;
  yahoo_symbol?: string | null; // exact Yahoo symbol (KR carries .KS/.KQ)
  name: string;
  market: Market;
  strategy_id: string;
  strategy_name: string;
  strength: number | null;
  grade: "A" | "B" | "C" | null;
  grade_value: number | null;
  confidence: number | null;
  regime_factor: number | null;
  price: number | null; // recommendation-day close
  entry_zone_top: number | null;
  stop_loss: number | null;
  take_profit: number | null;
  exit_mode: string;
  wyckoff_badge: string;
  reason: string;
  tags: string[];
  contrarian: string[];
  report_url: string | null;
}

export interface PaperSummary {
  start_equity: number;
  current_equity: number;
  total_return_pct: number;
  realized_return_pct: number;
  win_rate: number | null;
  profit_factor: number | null;
  max_drawdown_pct: number;
  n_closed: number;
  n_open: number;
  avg_holding: number | null;
  best: { ticker: string; return_pct: number } | null;
  worst: { ticker: string; return_pct: number } | null;
  period_start: string | null;
  period_end: string | null;
}

export interface EquityPoint {
  date: string;
  equity: number;
  drawdown_pct: number;
}

export interface PaperBlock {
  summary?: PaperSummary;
  equity_curve?: EquityPoint[];
  by_grade?: { key: string; n: number; win_rate: number; avg_return: number }[];
  open?: Record<string, unknown>[];
  recent_closed?: Record<string, unknown>[];
}

export interface AuditEntry {
  ts?: string;
  lever?: string;
  old?: unknown;
  new?: unknown;
  trigger?: string;
}

export interface SystemBlock {
  adaptive_loop_enabled: boolean;
  min_strength_send: number | null;
  enabled_strategies?: { strategy_id: string; name: string }[];
  effective_cutoff?: number | null;
  recent_audit?: AuditEntry[];
}

export interface Feed {
  schema_version: number;
  generated_at: string;
  signals: SignalCard[];
  paper: PaperBlock;
  system: SystemBlock;
}

export interface Quote {
  symbol: string;
  yahooSymbol?: string;
  price?: number;
  prevClose?: number | null;
  changePct?: number | null;
  currency?: string | null;
  name?: string | null;
  marketTime?: number | null;
  marketOpen?: boolean | null;
  error?: string;
}

export type QuoteMap = Record<string, Quote>;
