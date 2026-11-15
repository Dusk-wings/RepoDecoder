"use client";

import React from "react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "./button";
import { GoogleLogoIcon } from "@phosphor-icons/react";
import { Spinner } from "./spinner";

export default function GoogleButton() {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  async function GoogleAuth() {
    setError("");
    setLoading(true);

    const supabase = createClient();

    const { error } = await supabase.auth.signInWithOAuth({
      provider: "google",
      options: {
        redirectTo: `${window.location.origin}/authentication/callback?next=/dashboard`,
      },
    });

    if (error) {
      console.error("GOOGLE OAUTH FAILED");
      setError("Unable to continue with Google. Please try again.");
    }

    setLoading(false);
  }

  return (
    <span className="flex flex-col gap-1">
      {error != "" && <p className="text-xs text-error-color">* {error} *</p>}
      <Button onClick={GoogleAuth} disabled={loading}>
        <span>
          <GoogleLogoIcon size={32} color="#403f3f" weight="fill" />
        </span>
        <p>
          {loading ? (
            <span>
              <Spinner />
              <span>Processing ...</span>
            </span>
          ) : (
            "Continue with Google"
          )}
        </p>
      </Button>
    </span>
  );
}
