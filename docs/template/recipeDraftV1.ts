import { z } from "zod";

const FORBIDDEN_ORDER_KEYS = new Set(["step_number", "line_order"]);
const UUID_REGEX = /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const UuidSchema = z.string().regex(UUID_REGEX, "Invalid UUID");

type PathSegment = string | number;

const IngredientLineSchema = z
  .object({
    ingredient_id: UuidSchema,
    quantity_kind: z.enum(["exact", "approximate", "unquantified"]),
    input_qty: z.number().positive().optional().nullable(),
    input_unit_id: UuidSchema.optional().nullable(),
    note: z.string().optional().nullable(),
    raw_text: z.string().optional().nullable(),
    is_optional: z.boolean().optional().default(false),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hasQty = value.input_qty !== null && value.input_qty !== undefined;
    const hasUnit =
      value.input_unit_id !== null && value.input_unit_id !== undefined;

    if (value.quantity_kind === "unquantified") {
      if (hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty must be null or omitted for unquantified lines.",
        });
      }
      if (hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message:
            "input_unit_id must be null or omitted for unquantified lines.",
        });
      }
      return;
    }

    if (value.quantity_kind === "exact") {
      if (!hasQty) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_qty"],
          message: "input_qty is required for exact lines.",
        });
      }

      if (!hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: ["input_unit_id"],
          message: "input_unit_id is required for exact lines.",
        });
      }
      return;
    }

    if (value.quantity_kind === "approximate") {
      if (hasQty !== hasUnit) {
        ctx.addIssue({
          code: z.ZodIssueCode.custom,
          path: hasQty ? ["input_unit_id"] : ["input_qty"],
          message: "input_qty and input_unit_id must be provided together for approximate lines.",
        });
      }
    }
  });

const StepSchema = z
  .object({
    instruction: z.string().trim().min(1),
    ingredient_lines: z.array(IngredientLineSchema),
  })
  .strict();

const RecipeSchema = z
  .object({
    title: z.string().trim().min(1),
    description: z.string().optional().nullable(),
    notes: z.string().optional().nullable(),
    yield_units: z.number().min(1).optional().default(1),
    yield_phrase: z.string().optional().nullable(),
    yield_unit_name: z.string().optional().nullable(),
    yield_detail: z.string().optional().nullable(),
  })
  .strict();

export const RecipeDraftV1Schema = z
  .object({
    schema_v: z.literal(1),
    recipe: RecipeSchema,
    steps: z.array(StepSchema).min(1),
  })
  .strict()
  .superRefine((value, ctx) => {
    const hits: { path: PathSegment[]; key: string }[] = [];

    const scan = (current: unknown, path: PathSegment[]) => {
      if (Array.isArray(current)) {
        current.forEach((item, index) => scan(item, [...path, index]));
        return;
      }

      if (current && typeof current === "object") {
        for (const [key, child] of Object.entries(
          current as Record<string, unknown>,
        )) {
          if (FORBIDDEN_ORDER_KEYS.has(key)) {
            hits.push({ path: [...path, key], key });
          }
          scan(child, [...path, key]);
        }
      }
    };

    scan(value, []);

    hits.forEach((hit) => {
      ctx.addIssue({
        code: z.ZodIssueCode.custom,
        path: hit.path,
        message: `${hit.key} is server-derived and must not appear in drafts.`,
      });
    });
  });

export type RecipeDraftV1 = z.infer<typeof RecipeDraftV1Schema>;

export function parseRecipeDraftV1(input: unknown): RecipeDraftV1 {
  return RecipeDraftV1Schema.parse(input);
}

export function formatZodError(err: unknown): string {
  if (err instanceof z.ZodError) {
    return err.issues
      .map((issue) => {
        const path = issue.path.length ? issue.path.join(".") : "input";
        return `${path}: ${issue.message}`;
      })
      .join("\n");
  }

  if (err instanceof Error) {
    return err.message;
  }

  return "Unknown validation error.";
}
