"use client";

import React from "react";
import { createClient } from "@/lib/supabase/client";
import { Button } from "./ui/button";
import { GoogleLogoIcon } from "@phosphor-icons/react";
import { Spinner } from "./ui/spinner";

interface Props {
  disableActions: () => void;
  disabled: boolean;
}

export default function GoogleButton({ disableActions, disabled }: Props) {
  const [loading, setLoading] = React.useState(false);
  const [error, setError] = React.useState("");

  async function GoogleAuth() {
    disableActions();
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

    // setLoading(false);
  }

  return (
    <span className="flex flex-col gap-1">
      {error != "" && <p className="text-xs text-error-color">* {error} *</p>}
      <Button
        onClick={GoogleAuth}
        disabled={loading || disabled}
        variant="outline"
        className="p-4 flex gap-2"
      >
        {!loading && (
          <span>
            <GoogleLogoIcon
              size={28}
              // color={theme == "dark" ? "#ebfff2" : "#403f3f"}
              weight="fill"
            />
          </span>
        )}
        <p>
          {loading ? (
            <span className="flex flex-row gap-2 justify-center items-center">
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
