import { useEffect, useState } from "react";

/** False until the page's scripts are running; gate form submits on it. */
export function useHydrated() {
  const [hydrated, setHydrated] = useState(false);
  useEffect(() => setHydrated(true), []);
  return hydrated;
}
