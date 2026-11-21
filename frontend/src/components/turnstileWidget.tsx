"use client";

import { verificationFor } from "@/lib/verifyTurnstile";
import { Turnstile } from "@marsidev/react-turnstile";

interface Props {
  onVerify: (token: string) => void;
  action: verificationFor;
}

export default function TurnstileWidget({ onVerify, action }: Props) {
  return (
    <Turnstile
      siteKey={process.env.NEXT_PUBLIC_TURNSTILE_SITE_KEY!}
      onSuccess={onVerify}
      onExpire={() => onVerify("")}
      onError={() => onVerify("")}
      options={{
        action: action,
        theme: "auto",
        size: "flexible",
      }}
    />
  );
}
