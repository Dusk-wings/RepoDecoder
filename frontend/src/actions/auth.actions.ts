"use server";

import { createClient } from "@/lib/supabase/server";
import { validator } from "@/lib/validator";
import {
  loginValidator,
  registerValidation,
} from "@/validation/auth.validation";
import { redirect } from "next/navigation";

export async function singIn(formData: FormData) {
  const data = await validator(loginValidator, formData);

  if (data.success) {
    const supaBase = await createClient();
    const safe_data = data.data;

    const { error } = await supaBase.auth.signInWithPassword({
      email: String(safe_data.email),
      password: String(safe_data.password),
    });

    if (error) {
      console.error("SIGN IN FAILED:", error);

      switch (error.code) {
        case "email_not_confirmed":
          redirect("/login?error=email-confirmation");

        case "invalid_credentials":
          redirect("/login?error=invalid-credentials");

        case "user_banned":
          redirect("/login?error=account-restricted");

        default:
          redirect("/login?error=sign-in");
      }
    }

    redirect("/dashboard");
  } else {
    redirect("/login?error=validation");
  }
}

export async function singUp(formData: FormData) {
  const data = await validator(registerValidation, formData);

  if (data.success) {
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
          redirect("/register?error=email-exists");

        case "weak_password":
          redirect("/register?error=weak-password");

        case "signup_disabled":
        case "email_provider_disabled":
          redirect("/register?error=sign-up-disabled");

        default:
          redirect("/register?error=sign-up");
      }
    }

    if (!authData.session) {
      redirect("/register?message=check-email");
    }

    redirect("/dashboard");
  } else {
    redirect("/register?error=validation");
  }
}

export async function signInAnonymously() {
  const supabase = await createClient();

  const { error } = await supabase.auth.signInAnonymously();

  if (error) {
    console.error("ANONYMOUS SIGN IN FAILED:", error);

    redirect("/login?error=anonymous-sign-in");
  }

  redirect("/dashboard");
}