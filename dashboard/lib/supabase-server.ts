function supabaseConfig() {
  const url = (process.env.NEXT_PUBLIC_SUPABASE_URL ?? "").replace(/\/$/, "");
  const anonKey = process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY ?? "";

  if (!url || !anonKey) {
    throw new Error(
      "Supabase не настроен: нужны NEXT_PUBLIC_SUPABASE_URL и NEXT_PUBLIC_SUPABASE_ANON_KEY",
    );
  }
  return { url, anonKey };
}

function pgMetaConfig() {
  const url = (
    process.env.VITE_SUPABASE_URL ??
    process.env.NEXT_PUBLIC_SUPABASE_URL ??
    ""
  ).replace(/\/$/, "");
  const user = process.env.SUPABASE_STUDIO_USER ?? "";
  const password = process.env.SUPABASE_STUDIO_PASSWORD ?? "";

  if (!url || !user || !password) {
    throw new Error(
      "Supabase Studio не настроен: нужны VITE_SUPABASE_URL, SUPABASE_STUDIO_USER и SUPABASE_STUDIO_PASSWORD",
    );
  }
  return { url, user, password };
}

export async function supabaseRows<T>(
  table: string,
  params: Record<string, string>,
): Promise<T[]> {
  const { url, anonKey } = supabaseConfig();
  const endpoint = new URL(`${url}/rest/v1/${table}`);
  for (const [key, value] of Object.entries(params)) {
    endpoint.searchParams.set(key, value);
  }

  const response = await fetch(endpoint, {
    cache: "no-store",
    headers: {
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
      Accept: "application/json",
    },
  });
  if (!response.ok) {
    const details = (await response.text()).slice(0, 500);
    throw new Error(`Supabase ${table}: HTTP ${response.status}: ${details}`);
  }
  return response.json() as Promise<T[]>;
}

export async function supabaseRpc<T>(
  functionName: string,
  body: Record<string, unknown>,
): Promise<T> {
  const { url, anonKey } = supabaseConfig();
  const endpoint = `${url}/rest/v1/rpc/${functionName}`;
  const response = await fetch(endpoint, {
    method: "POST",
    cache: "no-store",
    headers: {
      apikey: anonKey,
      Authorization: `Bearer ${anonKey}`,
      Accept: "application/json",
      "Content-Type": "application/json",
    },
    body: JSON.stringify(body),
  });
  if (!response.ok) {
    const details = (await response.text()).slice(0, 500);
    throw new Error(
      `Supabase RPC ${functionName}: HTTP ${response.status}: ${details}`,
    );
  }
  return response.json() as Promise<T>;
}

export async function pgMetaQuery<T>(query: string): Promise<T[]> {
  const { url, user, password } = pgMetaConfig();
  const response = await fetch(
    `${url}/api/platform/pg-meta/default/query`,
    {
      method: "POST",
      cache: "no-store",
      headers: {
        Authorization: `Basic ${Buffer.from(`${user}:${password}`).toString("base64")}`,
        Accept: "application/json",
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ query }),
    },
  );
  if (!response.ok) {
    const details = (await response.text()).slice(0, 500);
    throw new Error(
      `Supabase pg-meta: HTTP ${response.status}: ${details}`,
    );
  }
  return response.json() as Promise<T[]>;
}
