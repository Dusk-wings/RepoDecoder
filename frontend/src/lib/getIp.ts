import { headers } from "next/headers";
import { NextRequest } from "next/server";

export function getClientIp(request: NextRequest) {
  const ip = request.headers.get("x-real-ip");

  if (!ip) {
    throw new Error("Unable to identify client IP");
  }

  return ip;
}

export async function getClientIpHeader(): Promise<string> {
  const headersList = await headers();

  const ip = headersList.get("x-real-ip");
  if (!ip) {
    throw new Error("Unable to identify client IP");
  }

  return ip;
}
