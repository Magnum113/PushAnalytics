import type { NextConfig } from "next";
import { loadEnvFile } from "node:process";
import { resolve } from "node:path";

if (
  !process.env.NEXT_PUBLIC_SUPABASE_URL ||
  !process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY
) {
  loadEnvFile(resolve(process.cwd(), "../.env"));
}

const nextConfig: NextConfig = {
  /* config options here */
};

export default nextConfig;
