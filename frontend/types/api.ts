export type ScanLeg = {
  K1: number;
  K2: number;
  premium: number;
  max_profit: number;
  max_loss: number;
  odds: number;
  pop?: number | null;
  quality?: string | null;
};

export type Bucket = {
  leg_type: "CALL" | "PUT";
  side: "DEBIT" | "CREDIT";
  top: ScanLeg[];
  bottom: ScanLeg[];
  expiry_ts?: number;      // bucket 所属到期（后端按 expiry 分组）
  expiry_date?: string;
};

export type ScanResp = {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number | null;
  dvol_index?: number | null;
  tenor: string;
  buckets: Bucket[];
};

export type DatesResp = {
  dates: string[];
};

export type ExpiriesResp = {
  date: string;
  base: string;
  expiries: number[];
};

export interface CSPCandidate {
  symbol: string;
  expiry_date: string;
  strike: number;
  delta: number;
  premium: number;
  breakeven: number;
  discount_pct: number;
  apr: number;
  assign_prob: number;
  oi: number;
  spread_bps: number;
  dte: number;
  score: number;
  quality: string;
}

export interface CSPResult {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number;
  dvol_index?: number;
  strategy: string;
  filters: Record<string, unknown>;
  candidates: CSPCandidate[];
}

export interface CCCandidate {
  symbol: string;
  expiry_date: string;
  strike: number;
  delta: number;
  premium: number;
  upside_pct: number;
  apr_notional: number;
  assign_prob: number;
  oi: number;
  spread_bps: number;
  dte: number;
  score: number;
  quality: string;
}

export interface CCResult {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number;
  dvol_index?: number;
  strategy: string;
  filters: Record<string, unknown>;
  candidates: CCCandidate[];
}

export interface OpinionResult {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number | null;
  dvol_index?: number | null;
  horizon: string;
  view: string;
  side: string;
  anchor_leg: string;
  anchor_strike: number;
  items: OpinionItem[];
  notes: {
    strike_snapped: boolean;
    original_target: number;
  };
}

export interface OpinionItem {
  expiry_ts: number;
  expiry_date: string;
  K1: number;
  K2: number;
  premium: number;
  max_profit: number;
  max_loss: number;
  odds: number;
}

// ---------------------------------------------------------------------------
// 多腿策略类型
// ---------------------------------------------------------------------------

export interface Leg {
  instrument: string;
  kind: string;
  side: string;
  strike: number;
  price: number;
  delta: number;
  iv: number;
  oi: number;
  spread_bps: number;
  t_years?: number;
}

export interface Greeks {
  net_delta: number;
  net_vega_usd: number;
  net_theta_usd: number;
}

export interface IronCondorCandidate {
  expiry_date: string;
  expiry_ts: number;
  dte: number;
  legs: Leg[];
  strikes: number[];
  credit: number;
  credit_usd: number;
  max_loss_usd: number;
  breakeven_lo: number;
  breakeven_hi: number;
  pop: number;
  roi_on_max_loss: number;
  apr_on_max_loss: number;
  im_standard_usd: number;
  liquidity_score: number;
  ivp_score: number;
  greeks: Greeks;
  score: number;
}

export interface IronCondorResult {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number;
  dvol_index?: number;
  strategy: string;
  ivp?: number | null;
  filters: Record<string, unknown>;
  candidates: IronCondorCandidate[];
}

export interface StrangleLongItem {
  expiry_date: string;
  expiry_ts: number;
  dte: number;
  legs: Leg[];
  strikes: number[];
  cost: number;
  cost_usd: number;
  breakeven_lo: number;
  breakeven_hi: number;
  move_required_pct: number;
  pop_profit: number;
  cost_ratio: number;
  vega_per_dollar: number;
  greeks: Greeks;
  liquidity_score: number;
  score: number;
}

export interface StrangleShortItem {
  expiry_date: string;
  expiry_ts: number;
  dte: number;
  legs: Leg[];
  strikes: number[];
  credit: number;
  credit_usd: number;
  breakeven_lo: number;
  breakeven_hi: number;
  pop: number;
  im_standard_usd: number;
  apr_on_im: number | null;
  tail_loss_est_usd: number;
  greeks: Greeks;
  liquidity_score: number;
  ivp_score: number;
  risk_warning: string;
  score: number;
}

export interface StrangleResult {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number;
  dvol_index?: number;
  strategy: string;
  ivp?: number | null;
  filters: Record<string, unknown>;
  long: StrangleLongItem[];
  short: StrangleShortItem[];
}

export interface CalendarCandidate {
  expiry_near: string;
  expiry_far: string;
  expiry_near_ts: number;
  expiry_far_ts: number;
  dte_near: number;
  dte_far: number;
  kind: string;
  strike: number;
  legs: Leg[];
  debit: number;
  debit_usd: number;
  atm_iv_near: number;
  atm_iv_far: number;
  iv_slope: number;
  iv_slope_ratio: number;
  net_theta_usd: number;
  theta_apr: number | null;
  net_vega_usd: number;
  debit_ratio: number;
  profit_zone: {
    breakeven_lo: number | null;
    breakeven_hi: number | null;
    max_profit_est: number;
    max_profit_spot: number;
  };
  liquidity_score: number;
  score: number;
}

export interface CalendarResult {
  asof_date: string;
  asof_ts: number;
  base: string;
  spot_price: number;
  dvol_index?: number;
  strategy: string;
  ivp?: number | null;
  filters: Record<string, unknown>;
  candidates: CalendarCandidate[];
}

export interface VolPanelData {
  base: string;
  date: string;
  dvol: number | null;
  ivp: number | null;
  ivr: number | null;
  days_available: number;
  term_structure: {
    expiry_ts: number;
    expiry_date: string;
    dte: number;
    atm_iv: number | null;
    rr25: number | null;
    bf25: number | null;
  }[];
  dvol_history: {
    ts: number;
    date: string;
    close: number | null;
  }[];
}
