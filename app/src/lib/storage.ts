import type { Market } from "../types";

export interface UserTicker {
  ticker: string;
  market: Market;
  added_date: string; // YYYY-MM-DD
  price_at_add: number | null;
}

const K_USER = "st.userTickers";
const K_HIDDEN = "st.hidden";
const K_PINNED = "st.pinned";

function read<T>(key: string, fallback: T): T {
  try {
    const v = localStorage.getItem(key);
    return v ? (JSON.parse(v) as T) : fallback;
  } catch {
    return fallback;
  }
}
function write(key: string, val: unknown): void {
  try {
    localStorage.setItem(key, JSON.stringify(val));
  } catch {
    /* quota / private mode — ignore */
  }
}

export const getUserTickers = (): UserTicker[] => read<UserTicker[]>(K_USER, []);
export function saveUserTickers(list: UserTicker[]): void {
  write(K_USER, list);
}
export function addUserTicker(t: UserTicker): UserTicker[] {
  const list = getUserTickers().filter((x) => x.ticker !== t.ticker);
  list.unshift(t);
  saveUserTickers(list);
  return list;
}
export function removeUserTicker(ticker: string): UserTicker[] {
  const list = getUserTickers().filter((x) => x.ticker !== ticker);
  saveUserTickers(list);
  return list;
}

export const getHidden = (): string[] => read<string[]>(K_HIDDEN, []);
export const getPinned = (): string[] => read<string[]>(K_PINNED, []);

function toggle(key: string, id: string): string[] {
  const set = new Set(read<string[]>(key, []));
  set.has(id) ? set.delete(id) : set.add(id);
  const arr = [...set];
  write(key, arr);
  return arr;
}
export const toggleHidden = (id: string): string[] => toggle(K_HIDDEN, id);
export const togglePinned = (id: string): string[] => toggle(K_PINNED, id);
