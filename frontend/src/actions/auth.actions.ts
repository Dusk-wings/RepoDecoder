"use server";

import { checkAuthCoolDown, checkEmailCooldown } from "@/lib/checkRateLimit";
import { getClientIpHeader } from "@/lib/getIp";
import { createClient } from "@/lib/supabase/server";
import { validator } from "@/lib/validator";
import { verifyTurnstile } from "@/lib/verifyTurnstile";
import {
  loginValidator,
  registerValidation,
  emailSchema,
} from "@/validation/auth.validation";
import { redirect } from "next/navigation";

async function rateLimiterHelper(email?: string) {
  let ip = null;
  try {
    ip = await getClientIpHeader();
  } catch {
    return {
      success: false,
      error: "server-error",
      message: "Internal Server Error",
    };
  }

  if (email) {
    const cooldown = await checkEmailCooldown(email);
    if (!cooldown.allowed) {
      return {
        success: false,
        error: "rate-limited",
        message: `Please wait for ${cooldown.retryAfter} s and then retry`,
        retry_after: cooldown.retryAfter,
      };
    }
  }

  const ip_cooldown = await checkAuthCoolDown(ip);

  if (!ip_cooldown.allowed) {
    return {
      success: false,
      error: "rate-limited",
      message: `Please wait for ${ip_cooldown.retryAfter} s and then retry`,
      retry_after: ip_cooldown.retryAfter,
    };
  }
}

export async function singIn(formData: FormData) {
  const data = await validator(loginValidator, formData);

  if (!data.success) {
    return {
      success: false,
      error: "validation",
      message: "Please check your information.",
    };
  }

  const safe_data = data.data;

  await rateLimiterHelper(safe_data.email);

  const supaBase = await createClient();

  const { error } = await supaBase.auth.signInWithPassword({
    email: String(safe_data.email),
    password: String(safe_data.password),
  });

  if (error) {
    console.error("SIGN IN FAILED:", error);

    switch (error.code) {
      case "email_not_confirmed":
        return {
          success: false,
          error: "email-confirmation",
          message: "Please confirm your email before signing in.",
        };

      case "invalid_credentials":
      case "user_banned":
        return {
          success: false,
          error: "undefined-credentials",
          message: "Unable to sign in. Please check your credentials",
        };

      default:
        return {
          success: false,
          error: "sign-in",
          message: "Unable to sign in. Please try again.",
        };
    }
  }

  redirect("/dashboard");
}

export async function singUp(formData: FormData, token: string) {
  const data = await validator(registerValidation, formData);

  if (data.success) {
    const isHuman = await verifyTurnstile(token, "sign_up");

    if (!isHuman) {
      return {
        success: false,
        error: "captcha-failed",
        message: "Verification failed. Please try again.",
      };
    }

    await rateLimiterHelper();

    const supaBase = await createClient();
    const safe_data = data.data;

    const { data: authData, error } = await supaBase.auth.signUp({
      email: String(safe_data.email),
      password: String(safe_data.password),
    });

    if (error) {
      console.error("SIGN UP FAILED:", error);

      switch (error.code) {
        case "user_already_exists":
        case "email_exists":
          return {
            success: false,
            error: "email-exists",
            message: "Email already exists. Please sign in.",
          };

        case "weak_password":
          return {
            success: false,
            error: "weak-password",
            message: "Password is too weak. Please choose a stronger password.",
          };

        case "signup_disabled":
        case "email_provider_disabled":
          return {
            success: false,
            error: "sign-up-disabled",
            message: "Sign up is currently disabled.",
          };

        default:
          return {
            success: false,
            error: "sign-up",
            message: "Unable to sign up. Please try again.",
          };
      }
    }

    if (!authData.session) {
      return {
        success: false,
        error: "email-confirmation",
        message: "Please check your email for a confirmation link.",
      };
    }

    redirect("/dashboard");
  } else {
    return {
      success: false,
      error: "validation",
      message: "Please check your information.",
    };
  }
}

export async function signInAnonymously(token: string | null) {
  if (!token) {
    return {
      success: false,
      error: "captcha-failed",
      message: "Verification failed. Please try again.",
    };
  }

  const isHuman = await verifyTurnstile(token, "anon_signin");

  if (!isHuman) {
    return {
      success: false,
      error: "captcha-failed",
      message: "Verification failed. Please try again.",
    };
  }

  // check for rate-limiting
  await rateLimiterHelper();

  const supabase = await createClient();

  const { error } = await supabase.auth.signInAnonymously();

  if (error) {
    console.error("ANONYMOUS SIGN IN FAILED:", error);

    return {
      success: false,
      error: "anon-sign-in",
      message: "Unable to sign in. Please try again.",
    };
  }

  redirect("/dashboard");
}

export async function resendConfirmationEmail(rawEmail: string) {
  const email = rawEmail.trim().toLowerCase();

  if (!emailSchema.safeParse(email).success) {
    return {
      success: false,
      error: "invalid-email",
      message: "Please enter a valid email address.",
    };
  }

  if (!email) {
    return {
      success: false,
      error: "invalid-email",
      message: "Please enter a valid email address.",
    };
  }

  await rateLimiterHelper(email);

  const supabase = await createClient();
  const origin = process.env.NEXT_PUBLIC_APP_URL ?? "http://localhost:3000";

  const { error } = await supabase.auth.resend({
    type: "signup",
    email,
    options: {
      emailRedirectTo: `${origin}/auth/callback`,
    },
  });

  if (error) {
    console.error("RESEND CONFIRMATION EMAIL FAILED:", error);

    if (error.code === "over_email_send_rate_limit") {
      return {
        success: false,
        error: "rate-limited",
        message: "Too many emails sent. Please wait a minute and try again.",
      };
    }

    return {
      success: false,
      error: "resend-confirmation-email",
      message: "Unable to resend confirmation email. Please try again.",
    };
  }

  return {
    success: true,
    message:
      "If an unconfirmed account exists for this email, a confirmation link has been sent.",
  };
}
