import { z } from "zod";

export async function validator<T extends z.ZodType>(scheam: T, rawData: FormData) {
  const raw = Object.fromEntries(rawData);
  const result = await scheam.safeParseAsync(raw);

  if (!result.success) {
    return {
      success: false as const,
      errors: z.treeifyError(result.error),
    };
  }

  const data = {
    success: true as const,
    data: result.data,
  };

  return data;
}
