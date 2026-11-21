"use client";

import { AlienIcon } from "@phosphor-icons/react";
import GoogleButton from "./googleButton";
import { Button } from "./ui/button";
import {
  Card,
  CardContent,
  CardDescription,
  CardFooter,
  CardHeader,
  CardTitle,
} from "./ui/card";
import { Checkbox } from "./ui/checkbox";
import { Input } from "./ui/input";
import { Label } from "./ui/label";
import React from "react";
import { usePathname, useRouter } from "next/navigation";
import {
  RegistrationValidation,
  LoginValidation,
  loginValidator,
  registerValidation,
} from "@/validation/auth.validation";
import { useForm } from "react-hook-form";
import { zodResolver } from "@hookform/resolvers/zod";
import {
  resendConfirmationEmail,
  singIn,
  signInAnonymously,
  singUp,
} from "@/actions/auth.actions";
import { verificationFor } from "@/lib/verifyTurnstile";
import { Dialog, DialogTrigger } from "./ui/dialog";
import TurnstilePopUp from "./turnstilePopUp";
import AlertPopup from "./alertPopup";
import { MailExclamationPoint } from "lucide-react";

interface Props {
  authenticationType: "SINGIN" | "SINGUP";
}

export default function AuthenticationForm({ authenticationType }: Props) {
  const {
    register,
    handleSubmit,
    formState: { errors, isSubmitting },
    setError,
  } = useForm<RegistrationValidation | LoginValidation>({
    resolver: zodResolver(
      authenticationType == "SINGIN" ? loginValidator : registerValidation,
    ),
    defaultValues: {
      email: "",
      password: "",
      confirmPassword: "",
    },
    mode: "onBlur",
    reValidateMode: "onChange",
  });
  const confirmPasswordError =
    "confirmPassword" in errors ? errors.confirmPassword : undefined;

  const [seconds, setSeconds] = React.useState(0);
  const [email, setEmail] = React.useState("");

  React.useEffect(() => {
    if (seconds <= 0) return;

    const timer = setInterval(() => {
      setSeconds((prev) => prev - 1);
    }, 1000);

    return () => clearInterval(timer);
  }, [seconds]);

  const [showPassword, setShowPassword] = React.useState(false);
  const [navigatingToGoogle, setNavigatingToGoogle] = React.useState(false);
  const [pendingData, setPendingData] =
    React.useState<RegistrationValidation | null>(null);
  const [showEmailAlert, setShowEmailAlert] = React.useState(false);
  const [token, setToken] = React.useState<string | null>(null);
  const [showCAPTCHA, setShowCAPTCHA] = React.useState<verificationFor | null>(
    null,
  );

  const [processing, setProcessing] = React.useState(false);
  const [open, setOpen] = React.useState(false);

  const router = useRouter();
  const pathName = usePathname();

  const [isPending, startTransition] = React.useTransition();

  const formDisabled =
    isPending || navigatingToGoogle || isSubmitting || processing;

  const handleNavigation = () => {
    if (isPending) return;

    const path = authenticationType === "SINGIN" ? "/register" : "/login";

    if (pathName === path) return;

    startTransition(() => {
      router.push(path);
    });
  };

  const onSubmit = async (data: RegistrationValidation | LoginValidation) => {
    if (authenticationType === "SINGUP") {
      const singupdata = data as RegistrationValidation;
      setOpen(true);
      setPendingData(singupdata);
      setShowCAPTCHA("sign_up");
    } else {
      const formData = new FormData();
      formData.append("email", data.email);
      formData.append("password", data.password);

      const result = await singIn(formData);

      if (!result.success) {
        if (result.error == "email-confirmation") {
          setEmail(data.email);
          setShowEmailAlert(true);
        } else {
          setError("root", {
            type: result.error,
            message: result.message,
          });
        }
      }
    }
  };

  const registerUser = async (data: RegistrationValidation) => {
    if (!token) {
      setError("root", {
        type: "captcha-failed",
        message: "Please fill the captcha to continue",
      });

      return;
    }

    const formData = new FormData();

    formData.append("email", data.email);
    formData.append("password", data.password);
    formData.append("confirmPassword", data.confirmPassword);

    const result = await singUp(formData, token);

    if (!result.success) {
      if (result.error == "email-confirmation") {
        setEmail(data.email);
        setShowEmailAlert(true);
      } else {
        setError("root", {
          type: result.error,
          message: result.message,
        });
      }
    }
  };

  const onCaptchaSuccess = async () => {
    try {
      setProcessing(true);
      if (showCAPTCHA == "anon_signin") {
        const result = await signInAnonymously(token);
        if (!result.success) {
          setError("root", {
            type: "anon-error",
            message: result.message,
          });
        }
      } else {
        if (!pendingData) {
          setError("root", {
            type: "fill-form",
            message: "Please fill the form to continue.",
          });
          return;
        }

        try {
          await registerUser(pendingData);
        } finally {
          setShowCAPTCHA(null);
          setPendingData(null);
        }
      }
    } finally {
      setOpen(false);
      setProcessing(false);
    }
  };

  const resendEmail = async () => {
    try {
      const result = await resendConfirmationEmail(email);
      if (!result.success) {
        if (result.error == "rate-limited") {
          const retryAfter =
            "retry_after" in result && typeof result.retry_after === "number"
              ? result.retry_after
              : 60;
          setSeconds(retryAfter || 60);
          return;
        }

        setError("root", {
          type: result.error,
          message: result.message,
        });
      } else {
        setSeconds(60);
      }
    } catch {
      setError("root", {
        type: "resend-email-failed",
        message: "Failed to resend confirmation email.",
      });
    }
  };

  return (
    <Dialog
      open={open}
      onOpenChange={(value) => {
        if (processing) return;
        setOpen(value);
      }}
    >
      <Card>
        <CardHeader>
          <CardTitle>
            {authenticationType == "SINGIN"
              ? "Login to your account"
              : "Create an account"}
          </CardTitle>
          <CardDescription>
            {authenticationType == "SINGIN"
              ? "Enter your email and password to login to your account"
              : "Enter your information below to create your account"}
          </CardDescription>
        </CardHeader>
        <CardContent>
          <form className="" onSubmit={handleSubmit(onSubmit)}>
            <TurnstilePopUp
              title={
                showCAPTCHA == "anon_signin"
                  ? "Continue as Guest ?"
                  : "Just making sure you're not a robot"
              }
              description="Pass this quick test so we know you're a real person."
              button_text={
                showCAPTCHA == "anon_signin" ? "Continue" : "Sign Up"
              }
              token={token}
              action={showCAPTCHA || "anon_signin"}
              setToken={setToken}
              activationFunction={onCaptchaSuccess}
              isProcessing={processing}
              setOpen={setOpen}
            />
            <div className="flex flex-col gap-6">
              {showEmailAlert && (
                <AlertPopup
                  title="Check your inbox"
                  description="We've sent you a confirmation link. Click it to verify your email and get started!"
                  variant="warning"
                  icon={MailExclamationPoint}
                >
                  <Button type="button" onClick={resendEmail} disabled={seconds > 0}>
                    {seconds > 0 ? `Resend (${seconds})` : "Resend"}
                  </Button>
                </AlertPopup>
              )}
              {errors.root && (
                <p
                  id="root-error"
                  role="alert"
                  className="text-xs text-destructive"
                >
                  {errors.root.message}
                </p>
              )}
              <div className="flex flex-col gap-2">
                <Label htmlFor="email">Email</Label>
                <Input
                  id="email"
                  type="email"
                  placeholder="jhondoe@example.com"
                  disabled={formDisabled}
                  aria-invalid={!!errors.email}
                  aria-describedby={errors.email ? "email-error" : undefined}
                  required
                  {...register("email")}
                />
                {errors.email && (
                  <p
                    id="email-error"
                    role="alert"
                    className="text-xs text-destructive"
                  >
                    {errors.email.message}
                  </p>
                )}
                {authenticationType == "SINGUP" && (
                  <p className="text-xs">We&apos;ll use this to contact you.</p>
                )}
              </div>
              <div className="flex flex-col gap-2">
                <Label htmlFor="password">Password</Label>
                <Input
                  id="password"
                  type={showPassword ? "text" : "password"}
                  placeholder="********"
                  disabled={formDisabled}
                  aria-invalid={!!errors.password}
                  aria-describedby={
                    errors.password ? "password-error" : undefined
                  }
                  required
                  {...register("password")}
                />
                {errors.password && (
                  <p
                    id="password-error"
                    role="alert"
                    className="text-xs text-destructive"
                  >
                    {errors.password.message}
                  </p>
                )}
                {authenticationType == "SINGUP" && (
                  <p className="text-xs">Must be at least 8 characters long.</p>
                )}
              </div>
              {authenticationType == "SINGUP" && (
                <div className="flex flex-col gap-2">
                  <Label htmlFor="confirm-password">Confirm Password</Label>
                  <Input
                    id="confirm-password"
                    type={showPassword ? "text" : "password"}
                    placeholder="********"
                    disabled={formDisabled}
                    aria-invalid={!!confirmPasswordError}
                    aria-describedby={
                      confirmPasswordError
                        ? "confirm-password-error"
                        : undefined
                    }
                    required
                    {...register("confirmPassword")}
                  />
                  {"confirmPassword" in errors && errors.confirmPassword && (
                    <p
                      id="confirm-password-error"
                      role="alert"
                      className="text-xs text-destructive"
                    >
                      {errors.confirmPassword.message}
                    </p>
                  )}
                </div>
              )}
              <div className="flex gap-2">
                <Checkbox
                  id="show-password"
                  name="show-pass"
                  checked={showPassword}
                  onCheckedChange={(e) => setShowPassword(e as boolean)}
                  disabled={formDisabled}
                />
                <Label htmlFor="show-password">Show Password</Label>
              </div>
              <div>
                <Button
                  // onClick={(e) => e.preventDefault()}
                  variant="default"
                  className="w-full p-4"
                  disabled={formDisabled}
                  type="submit"
                >
                  {authenticationType == "SINGIN" ? "Sign In" : "Sing Up"}
                </Button>
              </div>
            </div>
          </form>
        </CardContent>
        <CardFooter>
          <div className="flex flex-col gap-2">
            <GoogleButton
              disableActions={() => {
                setNavigatingToGoogle(true);
              }}
              disabled={isPending}
            />
            <div className="flex flex-col justify-center items-center gap-1">
              <DialogTrigger asChild>
                <Button
                  className="p-4 w-full flex gap-2"
                  variant="outline"
                  disabled={formDisabled}
                  onClick={() => {
                    setShowCAPTCHA("anon_signin");
                    setOpen(true);
                  }}
                >
                  <span>
                    <AlienIcon size={28} weight="fill" />
                  </span>
                  Continue as Guest
                </Button>
              </DialogTrigger>
              <p className="text-center font-stretch-extra-condensed  text-zinc-700 dark:text-zinc-300 text-xs">
                Stateless demo, Rate-limited preview, Sign up for RAG with
                higher context & memory
              </p>
            </div>
            <div className="flex justify-center items-center">
              <p>
                {authenticationType == "SINGIN"
                  ? "Don't have an account?"
                  : "Already have an account?"}
              </p>
              <Button
                variant="link"
                disabled={formDisabled}
                onClick={handleNavigation}
              >
                {authenticationType == "SINGIN" ? "Sing Up" : "Sign in"}
              </Button>
            </div>
          </div>
        </CardFooter>
      </Card>
    </Dialog>
  );
}
