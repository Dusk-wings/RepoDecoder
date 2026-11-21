import { Ratelimit } from "@upstash/ratelimit";
import { redis } from "./redis";

export const emailVereficationResend = new Ratelimit({
  redis,

  limiter: Ratelimit.slidingWindow(1, "1 m"),

  analytics: true,

  prefix: "repoDecoder:email-verefication-resend",
});


export const authentication = new Ratelimit({
  redis,

  limiter: Ratelimit.slidingWindow(6, "1 m"),

  analytics: true,

  prefix: "repoDecoder:authentication-ip",
});
