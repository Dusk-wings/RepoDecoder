import { createServerClient } from "@supabase/ssr";
import { NextResponse, type NextRequest } from "next/server";

export async function updateSession(request: NextRequest) {
  let response = NextResponse.next({ request });

  const supabase = createServerClient(
    process.env.NEXT_PUBLIC_SUPABASE_URL!,
    process.env.NEXT_PUBLIC_SUPABASE_PUBLISHABLE_KEY!,
    {
      cookies: {
        getAll() {
          return request.cookies.getAll();
        },
        setAll(cookiesToSet, headers) {
          cookiesToSet.forEach(({ name, value }) => {
            // Update request cookies for downstream server rendering.
            request.cookies.set(name, value);
          });

          // Create response with updated request.
          response = NextResponse.next({ request });

          cookiesToSet.forEach(({ name, value, options }) => {
            // Update browser cookies.
            response.cookies.set(name, value, options);
          });

          Object.entries(headers).forEach(([key, value]) => {
            // Preserve Supabase headers.
            response.headers.set(key, value);
          });
        },
      },
    },
  );

  // Refreshes the session when needed.
  await supabase.auth.getClaims();

  return response;
}
