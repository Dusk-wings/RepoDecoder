import { z } from "zod";

const passwordForRegistration = z
  .string()
  .min(8, { error: "Password must be at least 8 characters" })
  .regex(/[A-Z]/, { error: "Password must contain an uppercase letter" })
  .regex(/[a-z]/, { error: "Password must contain a lowercase letter" })
  .regex(/[0-9]/, { error: "Password must contain a number" })
  .regex(/[^A-Za-z0-9]/, {
    error: "Password must contain a special character",
  });

const minPasswordForValidation = z
  .string()
  .min(8, { error: "Password must be at least 8 characters" })
  .max(40, { error: "Password can contain max of 40 characters" });

export const loginValidator = z.object({
  email: z.email(),
  password: minPasswordForValidation,
});

export const registerValidation = z
  .object({
    email: z.email(),
    password: passwordForRegistration,
    confirmPassword: minPasswordForValidation,
  })
  .refine((data) => data.password == data.confirmPassword, {
    message: "Password don't match",
    path: ["confirmPassword"],
  });

export type RegistrationValidation = z.infer<typeof registerValidation>;
export type LoginValidation = z.infer<typeof loginValidator>;
