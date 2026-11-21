export type verificationFor =
  | "anon_signin"
  | "sign_up"
  | "sign_in"
  | "reset_password"
  | "delete_profile";

export async function verifyTurnstile(token: string, type: verificationFor) {
  if (!token) return false;

  const response = await fetch(
    "https://challenges.cloudflare.com/turnstile/v0/siteverify",
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({
        secret: process.env.TURNSTILE_SECRET_KEY,
        response: token,
      }),
      cache: "no-store",
    },
  );

  console.log(response);

  if (!response.ok) return false;

  const result = await response.json();

  return (
    result.success === true &&
    result.action === type &&
    result.hostname ===
      (process.env.NEXT_PUBLIC_TURNSTILE_HOSTNAME ?? "localhost")
  );
}
