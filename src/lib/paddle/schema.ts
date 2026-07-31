import { z } from "zod";

export const docParsingPageSchema = z
  .object({
    markdownText: z.string().default(""),
    markdownImages: z.record(z.string(), z.string()).default({}),
    outputImages: z.record(z.string(), z.string()).default({}),
    prunedResult: z.unknown().optional(),
    raw: z.unknown().optional()
  })
  .passthrough();

export const docParsingResultSchema = z
  .object({
    jobId: z.string(),
    pages: z.array(docParsingPageSchema),
    dataInfo: z.record(z.string(), z.unknown()).optional()
  })
  .passthrough();

export type SafeDocParsingResult = z.infer<typeof docParsingResultSchema>;

