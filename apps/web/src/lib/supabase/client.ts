import { createBrowserClient } from "@supabase/ssr";

/** Browser Supabase client. Uses only the public URL and anon key; the session lives in cookies. */
export function createClient() {
  return createBrowserClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_ANON_KEY!,
  );
}
