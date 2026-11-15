import { useCallback, useEffect, useRef, useState } from "react";
import { api, ApiError, getMerchantId } from "./api";

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState(!!path);
  const seq = useRef(0);

  const load = useCallback(async () => {
    if (!path) return;
    const my = ++seq.current;
    setLoading(true);
    try {
      const d = await api<T>(path);
      if (my === seq.current) { setData(d); setError(null); }
    } catch (e) {
      if (my === seq.current) { setError(e as ApiError); setData(null); }
    } finally {
      if (my === seq.current) setLoading(false);
    }
  }, [path, getMerchantId()]); // eslint-disable-line

  useEffect(() => { load(); }, [load, ...deps]); // eslint-disable-line
  return { data, error, loading, reload: load };
}

// Voice lives in voice.ts (Sarvam AI with a browser fallback); re-exported for older imports.
export { speak, stopSpeaking } from "./voice";
