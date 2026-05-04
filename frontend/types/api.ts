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
