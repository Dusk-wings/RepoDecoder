import {
  authentication,
  emailVereficationResend,
} from "@/lib/rateLimit";

export async function checkEmailCooldown(email: string) {
  const auth_key = "repoDecoder:email-verefication-resend:" + email;
  const cooldown = await emailVereficationResend.limit(auth_key);

  return {
    allowed: cooldown.success,
    limit: cooldown.limit,
    remaining: cooldown.remaining,
    retryAfter: Math.max(1, Math.ceil((cooldown.reset - Date.now()) / 1000)),
    reset: cooldown.reset,
  };
}



export async function checkAuthCoolDown(ip: string) {
  const auth_key = "repoDecoder:authentication-ip" + ip;

  const cooldown = await authentication.limit(auth_key);

  return {
    allowed: cooldown.success,
    limit: cooldown.limit,
    remaining: cooldown.remaining,
    retryAfter: Math.max(1, Math.ceil((cooldown.reset - Date.now()) / 1000)),
    reset: cooldown.reset,
  };
}
