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

interface Props {
  authenticationType: "SINGIN" | "SINGUP";
}

export default function AuthenticationForm({ authenticationType }: Props) {
  const [showPassword, setShowPassword] = React.useState(false);
  const router = useRouter();

  const pathName = usePathname();

  const [isPending, startTransition] = React.useTransition();
  const [navigatingToGoogle, setNavigatingToGoogle] = React.useState(false);

  const handleNavigation = () => {
    if (isPending) return;

    const path = authenticationType === "SINGIN" ? "/register" : "/login";

    if (pathName === path) return;

    startTransition(() => {
      router.push(path);
    });
  };

  return (
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
        <form className="">
          <div className="flex flex-col gap-6">
            <div className="flex flex-col gap-2">
              <Label htmlFor="email">Email</Label>
              <Input
                id="email"
                type="email"
                placeholder="jhondoe@example.com"
                name="email"
                disabled={isPending || navigatingToGoogle}
                required
              />
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
                name="password"
                disabled={isPending || navigatingToGoogle}
                required
              />
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
                  name="confirm-password"
                  disabled={isPending || navigatingToGoogle}
                  required
                />
              </div>
            )}
            <div className="flex gap-2">
              <Checkbox
                id="show-password"
                name="show-pass"
                checked={showPassword}
                onCheckedChange={(e) => setShowPassword(e as boolean)}
                disabled={isPending || navigatingToGoogle}
              />
              <Label htmlFor="show-password">Show Password</Label>
            </div>
            <div>
              <Button
                onClick={(e) => e.preventDefault()}
                variant="default"
                className="w-full p-4"
                disabled={isPending || navigatingToGoogle}
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
            <Button
              className="p-4 w-full flex gap-2"
              variant="outline"
              disabled={isPending || navigatingToGoogle}
            >
              <span>
                <AlienIcon size={28} weight="fill" />
              </span>
              Continue as Guest
            </Button>
            <p className="text-center font-stretch-extra-condensed  text-zinc-700 dark:text-zinc-300 text-xs">
              Stateless demo, Rate-limited preview, Sign up for RAG with higher
              context & memory
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
              disabled={isPending || navigatingToGoogle}
              onClick={handleNavigation}
            >
              {authenticationType == "SINGIN" ? "Sing Up" : "Sign in"}
            </Button>
          </div>
        </div>
      </CardFooter>
    </Card>
  );
}
